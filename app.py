"""极简拖拽转录台：把 webm（或任何音视频）拖进窗口 → 自动解码并实时出 transcript。

依赖本地 faster-whisper + CUDA（见 transcribe.py）。启动：pythonw app.py
"""

from __future__ import annotations

import ctypes
import queue
import re
import sys
import threading
import traceback
from pathlib import Path


def _dpi_aware() -> None:
    """必须在建窗前声明：系统缩放非 100% 时否则界面被位图拉伸、文字发虚。"""
    if sys.platform != "win32":
        return
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(-4):  # per-monitor v2
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_dpi_aware()

import tkinter as tk  # noqa: E402
from tkinter import filedialog, messagebox  # noqa: E402

from tkinterdnd2 import DND_FILES, TkinterDnD  # noqa: E402

import env  # noqa: E402
import languages as LG  # noqa: E402
import transcribe as T  # noqa: E402

# ---------- 配色：淡色块 + 细色条，不做饱和填充 ----------
BG = "#FBFAF7"
CARD = "#F3F0E9"
FG = "#2B2A27"
MUTED = "#8C8577"
LINE = "#DED8CB"
ACCENT = "#7FA6C4"      # 淡蓝：进度
OK = "#8FA97C"          # 淡绿：完成
ERR = "#C09082"         # 淡赭：错误
FONT = env.ui_font()
IDLE_TITLE = "等待文件"
IDLE_STATUS = "拖入即自动解码并转写，全程在本机完成"

VIDEO_EXT = {".webm", ".mp4", ".mov", ".mkv", ".avi", ".wmv", ".flv", ".m4v", ".mp3",
             ".wav", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wma", ".amr"}


def parse_drop(data: str) -> list[str]:
    """解析拖放数据：{带空格 的路径} 无空格的路径 → 列表。

    不能用 tk.splitlist：Tcl 会把 Windows 路径里的 \\t \\n 等当转义符吃掉
    （例如 C:\\\\temp\\\\x.webm 变成 TABemp）。这里只做字面切分。
    """
    out: list[str] = []
    i, n = 0, len(data)
    while i < n:
        while i < n and data[i] in " \t\n":
            i += 1
        if i >= n:
            break
        if data[i] == "{":
            j = i + 1
            buf = []
            while j < n:
                if data[j] == "\\" and j + 1 < n and data[j + 1] in "{}":
                    buf.append(data[j + 1])
                    j += 2
                    continue
                if data[j] == "}":
                    break
                buf.append(data[j])
                j += 1
            out.append("".join(buf))
            i = j + 1
        else:
            j = i
            while j < n and data[j] not in " \t\n":
                j += 1
            out.append(data[i:j])
            i = j
    return out


def out_dir_for(src: Path) -> Path:
    """结果优先落在源文件旁边的「转录结果」文件夹；不可写则退回数据目录。"""
    cand = src.parent / "转录结果"
    try:
        cand.mkdir(parents=True, exist_ok=True)
        probe = cand / ".w2t"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return cand
    except OSError:
        fallback = Path(env.data_dir()) / "output"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


class App:
    FORMATS = {
        "Word 文档 · 自动排版": ("docx", "blocks"),
        "Word 文档 · 逐句对照": ("docx", "lines"),
        "纯文本 .txt": ("txt", None),
        "Markdown .md": ("md", None),
        "字幕 .srt": ("srt", None),
        "字幕 .vtt": ("vtt", None),
        "数据 .json": ("json", None),
    }

    def __init__(self, root: TkinterDnD.Tk):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.stop_flag = threading.Event()
        self.files: list[Path] = []
        self.index = 0
        self.result: T.Result | None = None
        self.last_saved: Path | None = None
        self._want_bi = False
        self._want_tgt = "zh"
        self.lang = ""          # 空串＝自动检测
        self.tgt = "zh"         # 译文语言

        root.title("拖拽转录")
        root.configure(bg=BG)
        # 按屏幕比例给初始尺寸：高分屏/高缩放下也不会显得局促
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{int(sw * 0.55)}x{int(sh * 0.70)}+90+60")
        root.minsize(660, 460)
        root.drop_target_register(DND_FILES)
        root.dnd_bind("<<Drop>>", self.on_drop)
        root.after(80, self.poll)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.build()

    # ---------- 界面 ----------
    def build(self):
        # 顶部：文件与状态
        top = self.top = self._card(self.root, padx=14, pady=10)
        top.pack(fill="x", padx=14, pady=(14, 6))
        self.title_lbl = self._lbl(top, IDLE_TITLE, 12, FG, "bold")
        self.title_lbl.pack(anchor="w")
        self.status_lbl = self._lbl(top, IDLE_STATUS, 9, MUTED)
        self.status_lbl.pack(anchor="w", pady=(2, 0))
        # 进度：2px 细色条
        self.bar = self._canvas(top, 2)
        self.bar.pack(fill="x", pady=(9, 0))
        self._bar_bg = self.bar.create_rectangle(0, 0, 900, 2, fill=CARD, width=0)
        self._bar_fg = self.bar.create_rectangle(0, 0, 0, 2, fill=ACCENT, width=0)

        # 中部：拖放提示 / 文本
        mid = self.mid = self._card(self.root, padx=0, pady=0)
        mid.pack(fill="both", expand=True, padx=14, pady=6)
        self.hint = self._lbl(mid, "把 webm 拖进来", 20, MUTED, "normal")
        self.hint.place(relx=0.5, rely=0.44, anchor="center")
        self.sub = self._lbl(mid, "本地离线解码与转写 · 支持 webm / mp4 / mov / mp3 / wav", 10, MUTED)
        self.sub.place(relx=0.5, rely=0.44, anchor="center", y=42)
        self.pick = self._lbl(mid, "或点击选择文件", 10, ACCENT)
        self.pick.place(relx=0.5, rely=0.44, anchor="center", y=74)
        self.pick.config(cursor="hand2")
        self.pick.bind("<Button-1>", lambda e: self.on_pick())
        self.pick.bind("<Enter>", lambda e: self.pick.config(fg=FG))
        self.pick.bind("<Leave>", lambda e: self.pick.config(fg=ACCENT))
        self._hint_pair = (self.hint, self.sub, self.pick)

        self.text = self._text(mid)
        self.text.pack(fill="both", expand=True, padx=12, pady=10)
        self.text.pack_forget()  # 初始隐藏，拖入后显示

        # 底部：语言、保存、复制
        bot = self.bot = self._card(self.root, padx=14, pady=10)
        bot.pack(fill="x", padx=14, pady=(6, 14))
        self._lbl(bot, "转写", 9, MUTED).pack(side="left")
        self.lang_var = tk.StringVar(value="自动检测")
        self._menu(bot, self.lang_var, ["自动检测"] + LG.choices(), self._set_lang, 10)\
            .pack(side="left", padx=(5, 12))
        self.bi = tk.StringVar(value="")
        cb = tk.Checkbutton(bot, text="双语", variable=self.bi, onvalue="on", offvalue="",
                            bg=CARD, fg=FG, activebackground=CARD, activeforeground=FG,
                            selectcolor=BG, relief="flat", highlightthickness=0,
                            font=(FONT, 9), cursor="hand2")
        cb.pack(side="left", padx=(2, 14))
        self._lbl(bot, "译为", 9, MUTED).pack(side="left")
        self.tgt_var = tk.StringVar(value="简体中文")
        self._menu(bot, self.tgt_var, LG.choices(), self._set_tgt, 10)\
            .pack(side="left", padx=(5, 12))
        self._btn(bot, "复制全部", self.copy_all).pack(side="left", padx=(0, 6))
        exp = tk.Menubutton(bot, text="导出 ▾", bg=CARD, fg=FG, relief="flat", bd=0,
                            cursor="hand2", font=(FONT, 9), padx=11, pady=4,
                            highlightthickness=1, highlightbackground=LINE,
                            activebackground=LINE)
        menu = tk.Menu(exp, tearoff=0, font=(FONT, 9), bg=BG, fg=FG,
                       activebackground=LINE, borderwidth=0)
        for label in self.FORMATS:
            menu.add_command(label=label, command=lambda l=label: self.export(l))
        exp["menu"] = menu
        exp.pack(side="left")
        self._btn(bot, "打开文件夹", self.open_out).pack(side="left", padx=(6, 0))
        self.stop_btn = self._btn(bot, "停止", self.request_stop, ERR)
        self.stop_btn.pack_forget()
        self._btn(bot, "清空", self.clear, MUTED).pack(side="right")

    def _card(self, parent, padx, pady):
        return tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=LINE,
                        bd=0)

    def _lbl(self, parent, text, size, color, weight="normal"):
        return tk.Label(parent, text=text, bg=parent["bg"], fg=color,
                        font=(FONT, size, weight) if weight != "normal" else (FONT, size),
                        anchor="w", justify="left")

    def _canvas(self, parent, h):
        return tk.Canvas(parent, height=h, bg=parent["bg"], highlightthickness=0, bd=0)

    def _text(self, parent):
        t = tk.Text(parent, bg=BG, fg=FG, wrap="word", relief="flat", bd=0, undo=False,
                    font=(FONT, 10), insertbackground=FG, selectbackground="#E3E7EA",
                    padx=4, pady=4, spacing3=5, height=6)
        t.tag_config("dim", foreground=MUTED, font=(FONT, 9))
        t.config(state="disabled")
        return t

    def _btn(self, parent, label, cmd, color=FG):
        b = tk.Button(parent, text=label, command=cmd, bg=CARD, fg=color,
                      activebackground=LINE, relief="flat", bd=0, cursor="hand2",
                      font=(FONT, 9), padx=11, pady=4, highlightthickness=1,
                      highlightbackground=LINE)
        return b

    def _menu(self, parent, var, values, cmd, width):
        """统一样式的下拉框。"""
        box = tk.OptionMenu(parent, var, *values, command=cmd)
        box.config(bg=CARD, fg=FG, activebackground=CARD, relief="flat", width=width,
                   font=(FONT, 9), highlightthickness=1, highlightbackground=LINE,
                   indicatoron=False)
        box["menu"].config(font=(FONT, 9), bg=BG, fg=FG)
        return box

    def _set_lang(self, v):
        self.lang = LG.code_of(v)          # 「自动检测」映射成空串

    def _set_tgt(self, v):
        self.tgt = LG.code_of(v) or "zh"

    # ---------- 拖放 ----------
    def on_drop(self, event):
        if self.busy:
            self.set_status("当前任务进行中，请等待完成后再拖入")
            return
        self.accept([Path(raw) for raw in parse_drop(event.data)])

    def on_pick(self):
        if self.busy:
            return
        raw = filedialog.askopenfilenames(
            title="选择音视频文件",
            filetypes=[("媒体文件", "*.webm *.mp4 *.mov *.mkv *.avi *.m4v *.mp3 "
                                  "*.wav *.m4a *.aac *.ogg *.opus *.flac *.wma"),
                       ("所有文件", "*.*")])
        if raw:
            self.accept([Path(p) for p in parse_drop(raw)])

    def accept(self, paths):
        """过滤出可处理的媒体文件并开始排队转录。"""
        media = [p for p in paths if p.suffix.lower() in VIDEO_EXT and p.exists()]
        if not media:
            self.set_status("只接受音视频文件（webm / mp4 / mov / mp3 …）")
            return
        self.files = media
        self.index = 0
        self.show_text_area()
        self._enqueue()

    def _enqueue(self):
        p = self.files[self.index]
        lang = self.lang or None
        self.busy = True
        self.stop_flag.clear()
        self.result = None
        self.stop_btn.pack(side="left", padx=(10, 0))
        tag = f"{self.index + 1}/{len(self.files)} · " if len(self.files) > 1 else ""
        self.set_title(f"{tag}{p.name}")
        self.set_status("解码音频 → 首次需加载模型（约 30 秒）→ 开始转写")
        self.clear_text()
        size = self.root.winfo_width()
        self.bar.coords(self._bar_bg, 0, 0, max(size, 1), 2)
        # tk 变量只能在主线程读，先取成普通字段给后台线程用
        self._want_bi = self.bi.get() == "on"
        self._want_tgt = self.tgt

        def worker():
            try:
                r = T.transcribe(
                    p, lang,
                    on_progress=lambda done, total: self.q.put(("progress", done, total)),
                    on_segment=lambda s: self.q.put(("seg", s)),
                    should_stop=self.stop_flag.is_set,
                    on_note=lambda m: self.q.put(("note", m)),
                )
                if self._want_bi and r.segments and not self.stop_flag.is_set():
                    r.translations = self._translate(r)
                    if r.translations:
                        r.tgt_lang = self._want_tgt
                self.q.put(("done", r))
            except Exception as e:
                self.q.put(("error", f"{e}\n{traceback.format_exc(limit=1)}"))

        threading.Thread(target=worker, daemon=True).start()

    def _translate(self, r):
        """转录完接着做离线翻译；失败就退回纯原文，不毁掉整次结果。"""
        import translate

        try:
            return translate.translate_pairs(
                r.paired(), (r.language or "es")[:2], self._want_tgt,
                on_progress=lambda done, total: self.q.put(("progress", done, total)),
                should_stop=self.stop_flag.is_set)
        except Exception as e:
            self.q.put(("note", f"翻译未完成：{type(e).__name__}: {str(e)[:120]}"))
            return []

    # ---------- 轮询后台事件 ----------
    def poll(self):
        try:
            while True:
                kind, *data = self.q.get_nowait()
                if kind == "note":
                    self.set_status(data[0])
                elif kind == "seg":
                    self.append_seg(data[0])
                elif kind == "progress":
                    done, total = data
                    frac = min(max(done / total, 0), 1) if total else 0
                    w = self.bar.winfo_width()
                    self.bar.coords(self._bar_fg, 0, 0, w * frac, 2)
                    if total:
                        self.set_status(f"转写中 {frac * 100:.0f}%   "
                                        f"{T.fmt_hms(done)} / {T.fmt_hms(total)}")
                elif kind == "done":
                    self.finish(data[0])
                elif kind == "error":
                    self.fail(data[0])
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def finish(self, r: T.Result):
        self.result = r
        self.busy = False
        self.stop_btn.pack_forget()
        n = len(r.segments)
        saved = self.auto_export() if n else None
        self.set_status(f"完成 · {n} 句 · {r.language} · 时长 {T.fmt_hms(r.duration)}"
                        + (f" · 已存 {saved.name}" if saved else ""))
        if n == 0:
            self.text.config(state="normal")
            self.text.insert("end", "\n（未识别到语音内容）\n")
            self.text.config(state="disabled")
        # 多文件：继续下一个
        if self.index + 1 < len(self.files):
            self.index += 1
            self._after_next()

    def _after_next(self):
        # 让 UI 先刷新，再启动下一段
        self.root.after(300, self._enqueue)

    def fail(self, msg: str):
        self.busy = False
        self.stop_btn.pack_forget()
        self.set_status("失败")
        self.text.config(state="normal")
        self.text.insert("end", "\n" + str(msg).strip() + "\n")
        self.text.config(state="disabled")
        self.bar.itemconfig(self._bar_fg, fill=ERR)

    def request_stop(self):
        self.stop_flag.set()
        self.set_status("已停止")

    # ---------- 文本区 ----------
    def _hints(self, show: bool):
        """提示三件套（大标题 / 说明 / 选择文件）的显隐。"""
        for i, w in enumerate(self._hint_pair):
            if show:
                w.place(relx=0.5, rely=0.44, anchor="center", y=(0, 42, 74)[i])
            else:
                w.place_forget()

    def show_text_area(self):
        self._hints(False)
        self.text.pack(fill="both", expand=True, padx=12, pady=10)

    def clear_text(self):
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        self.text.config(state="disabled")
        self.bar.coords(self._bar_fg, 0, 0, 0, 2)
        self.bar.itemconfig(self._bar_fg, fill=ACCENT)

    def append_seg(self, s: T.Segment):
        if not s.text:
            return
        at_bottom = self.text.yview()[1] >= 0.995
        self.text.config(state="normal")
        self.text.insert("end", f"[{T.fmt_ts(s.start)}]  ", ("dim",))
        self.text.insert("end", s.text + "\n")
        self.text.config(state="disabled")
        if at_bottom:
            self.text.see("end")

    # ---------- 输出 ----------
    def copy_all(self):
        if not self.result or not self.result.segments:
            self.set_status("还没有内容可复制")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.result.plain)
        self.set_status("已复制到剪贴板")

    def write_to(self, path, ext: str, mode: str | None = None) -> None:
        """把当前结果写成指定格式（docx 走自动排版）。"""
        if ext == "docx":
            import docx_export

            docx_export.save(self.result, path, mode=mode or "blocks")
        else:
            Path(path).write_text(T.render_text(self.result, ext), encoding="utf-8")

    def out_dir(self) -> Path:
        """当前源文件对应的输出目录。"""
        src = self.files[self.index] if self.files else Path.cwd()
        return out_dir_for(src)

    def auto_export(self) -> Path | None:
        """转完自动落一套文件，用户不必再点导出。"""
        try:
            files = T.write_outputs(self.result, self.out_dir(), ("docx", "txt", "srt"))
        except Exception as e:
            self.set_status(f"自动保存失败：{e}")
            return None
        docx = next((f for f in files if f.suffix == ".docx"), files[0] if files else None)
        self.last_saved = docx
        return docx

    def open_out(self):
        """在资源管理器/Finder 里定位结果文件。"""
        target = self.last_saved or self.out_dir()
        try:
            env.open_path(target)
        except Exception as e:
            self.set_status(f"打不开：{e}")

    def export(self, label: str):
        """按菜单项导出，docx 走自动排版。"""
        if not self.result or not self.result.segments:
            self.set_status("还没有内容可保存")
            return
        ext, mode = self.FORMATS[label]
        base = re.sub(r'[<>:"/\\|?*]', "_", self.result.source.name.rsplit(".", 1)[0])[:80]
        suffix = "·逐句" if mode == "lines" else ""
        path = filedialog.asksaveasfilename(
            title=label, defaultextension=f".{ext}",
            initialfile=f"{base}{suffix}.{ext}",
            filetypes=[(label, f"*.{ext}"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            self.write_to(path, ext, mode)
        except Exception as e:
            self.set_status(f"导出失败：{e}")
            return
        self.set_status(f"已导出 → {path}")

    def clear(self):
        if self.busy:
            return
        self.files, self.index, self.result = [], 0, None
        self.clear_text()
        self.set_title(IDLE_TITLE)
        self.set_status(IDLE_STATUS)
        self.text.pack_forget()
        self._hints(True)

    # ---------- 小工具 ----------
    def set_title(self, t):
        self.title_lbl.config(text=t)

    def set_status(self, t):
        self.status_lbl.config(text=t)

    def on_close(self):
        self.stop_flag.set()
        self.root.destroy()


def log_line(msg: str) -> None:
    """无界面模式下出错要有地方可查：追加到数据目录的日志。"""
    try:
        p = Path(env.data_dir()) / "transcriber.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        import datetime

        with p.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%F %T} {msg}\n")
    except OSError:
        pass


def cli_mode(paths) -> bool:
    """文件作为参数传入（含拖到程序图标上）：不开界面，直接转写落盘。"""
    errs = []
    log_line(f"CLI 开始：{len(paths)} 个文件 · {env.summary()}")
    for p in paths:
        try:
            res = T.transcribe(Path(p))
            files = T.write_outputs(res, out_dir_for(Path(p)), ("docx", "txt", "srt"))
            log_line(f"完成 {p.name}：{len(res.segments)} 句 → {files[0]}")
        except Exception as e:
            errs.append(f"{Path(p).name}：{e}")
            log_line(f"失败 {p.name}：{e}\n{traceback.format_exc()}")
    if errs:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("转写失败", "\n".join(errs)[:1200])
            root.destroy()
        except Exception:
            pass
    return not errs


def main():
    given = [Path(a) for a in sys.argv[1:]
             if Path(a).suffix.lower() in VIDEO_EXT and Path(a).exists()]
    if given:
        sys.exit(0 if cli_mode(given) else 1)
    root = TkinterDnD.Tk()
    ui = App(root)
    if not env.has_model():
        ui.set_status(f"首次转写会先下载模型（约 1.6GB，只需一次）→ {env.data_dir()}")
    if not env.find_ffmpeg_or_av():
        messagebox.showwarning(
            "缺少解码组件",
            "这台机器还无法解码音频。\n\n"
            "Windows：把 ffmpeg.exe 放进本程序目录，或安装后加入 PATH\n"
            "macOS：brew install ffmpeg　　Linux：sudo apt install ffmpeg\n\n"
            "也可以用环境变量 W2T_FFMPEG 指向可执行文件。")
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 打包成无控制台程序后，崩溃也要留痕
        log_line(f"启动失败：{e}\n{traceback.format_exc()}")
        raise
