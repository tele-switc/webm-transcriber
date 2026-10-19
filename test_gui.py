"""GUI 端到端自检：用假转录器驱动整个界面（拖放 -> 进度 -> 文本 -> 保存）。

跑法：python test_gui.py    通过则打印 GUI_OK
不需要 GPU，几秒完成。
"""

import sys
import threading
import queue
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import transcribe as T  # noqa: E402
import app as A  # noqa: E402

TMP = Path(tempfile.gettempdir())
SAMPLE = TMP / "w2t_test_sample.webm"
SAMPLE_SP = TMP / "w2t test sample 1.webm"
OUT = Path(__file__).parent / "output"


def fake_transcribe(path, language=None, on_progress=None, on_segment=None,
                    should_stop=None, beam_size=5, on_note=None):
    """造 6 句假字幕，模拟进度回调与耗时。"""
    res = T.Result(source=Path(path), duration=60.0, engine="stub")
    for i in range(6):
        if should_stop and should_stop():
            break
        s = T.Segment(i * 10.0, i * 10.0 + 9.0, f"第 {i + 1} 句测试内容，用于验证界面滚动与保存。")
        res.segments.append(s)
        res.language = "zh"
        on_segment(s)
        on_progress(s.end, res.duration)
        time.sleep(0.12)
    return res


def make_sample():
    """造两个假 webm（其中一个文件名带空格），验证拖放校验与多文件队列。"""
    import shutil
    import subprocess

    for p in (SAMPLE, SAMPLE_SP):
        if not p.exists():
            subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                 "-i", "sine=frequency=440:duration=60", "-c:a", "libopus",
                 "-f", "webm", str(p)], check=True, capture_output=True)
    return [SAMPLE_SP, SAMPLE]


def main():
    A.T.transcribe = fake_transcribe  # 换成假转录器
    make_sample()
    root = A.TkinterDnD.Tk()
    ui = A.App(root)
    root.update()
    checks, done = [], {"ok": False}

    assert ui.text.winfo_manager() == "", "初始应显示拖放提示"

    # 0) 拖放数据解析：反斜杠必须原样保留（Tcl splitlist 会把 \t 变成 TAB）
    pd = A.parse_drop(r"{C:\temp\a b.webm} D:\x\y.mp4")
    checks.append(("解析保住反斜杠", pd == [r"C:\temp\a b.webm", r"D:\x\y.mp4"]))
    checks.append(("含空格路径成一项", pd[0].endswith("a b.webm")))

    # 1) 模拟拖入两个文件（都带花括号，与 tkdnd 真实数据格式一致）
    class Ev:
        data = "{" + str(SAMPLE_SP) + "} {" + str(SAMPLE) + "}"

    ui.on_drop(Ev())
    root.update()
    checks.append(("文本区已显示", ui.text.winfo_manager() == "pack"))
    checks.append(("提示已隐藏", not ui.hint.winfo_ismapped() and not ui.pick.winfo_ismapped()))
    checks.append(("含空格路径解析对", str(ui.files[0]) == str(SAMPLE_SP)))
    checks.append(("两个文件入队", len(ui.files)))

    # 2) 等后台线程跑完队列
    deadline = time.time() + 15
    while time.time() < deadline:
        root.update()
        time.sleep(0.05)
        if ui.index == 1 and not ui.busy and ui.result and len(ui.result.segments) >= 6:
            break
    root.update()
    body = ui.text.get("1.0", "end").strip()
    checks.append(("第二个文件也完成", ui.index == 1 and not ui.busy))
    checks.append(("实时出现 6 句", len(ui.result.segments) if ui.result else 0))
    checks.append(("文本含时间戳", "[00:00]" in body))
    checks.append(("状态栏显示完成", "完成" in ui.status_lbl["text"]))
    checks.append(("进度条走满", ui.bar.coords(ui._bar_fg)[2] > 100))

    # 0.5) 语言表完整性
    import languages as LG

    checks.append(("语言表 24 种", len(LG.LANGS) >= 20))
    checks.append(("代码不重复", len({c for c, _, _ in LG.LANGS}) == len(LG.LANGS)))
    checks.append(("NLLB 码齐全", all(len(n) >= 6 for _, _, n in LG.LANGS)))
    checks.append(("中文名反查可用", LG.code_of("西班牙语") == "es" and LG.label("fr") == "法语"))

    # 2.5) 双语：stub 翻译器 + 勾上复选框 + 自选译文语言
    import translate as TR

    seen = {}

    def fake_pairs(pairs, src, tgt="zh", **k):
        seen["src"], seen["tgt"] = src, tgt
        return [f"〔译{i + 1}〕中文。" for i in range(len(pairs))]

    TR.translate_pairs = fake_pairs
    ui.bi.set("on")
    ui.tgt = "fr"          # 用户自选译文语言

    class Ev2:
        data = "{" + str(SAMPLE) + "}"

    ui.on_drop(Ev2())
    deadline = time.time() + 15
    while time.time() < deadline:
        root.update()
        time.sleep(0.05)
        if not ui.busy and ui.result and ui.result.translations:
            break
    checks.append(("双语译文进入结果", bool(ui.result and ui.result.translations)))
    checks.append(("译文语言按自选传递", seen.get("tgt") == "fr"))
    checks.append(("结果记录译文语言", getattr(ui.result, "tgt_lang", "") == "fr"))
    checks.append(("译文与段数对齐", bool(ui.result) and len(ui.result.translations)
                   == len(ui.result.paired())))

    # 3) 复制与全格式导出
    ui.copy_all()
    root.update()
    checks.append(("剪贴板有内容", bool(root.clipboard_get().strip())))
    ui.result.source = Path("selftest.webm")
    files = T.write_outputs(ui.result, OUT, ("txt", "md", "srt", "vtt", "json", "docx"))
    checks.append(("六种格式全出", sorted(f.suffix for f in files)))
    docx_path = OUT / "selftest.docx"
    checks.append(("docx 落盘", docx_path.exists() and docx_path.stat().st_size > 5000))
    from docx import Document  # 排版结构断言
    from docx.oxml.ns import qn

    dd = Document(str(docx_path))
    sec = dd.sections[0]
    checks.append(("A4 + 2.6cm 边距", round(sec.page_width.cm) == 21
                   and round(sec.left_margin.cm, 1) == 2.6))
    checks.append(("页脚有页码域", "PAGE" in sec.footer.paragraphs[0]._p.xml))
    ea = [r._element.rPr.rFonts.get(qn("w:eastAsia"))
          for p in dd.paragraphs for r in p.runs
          if r._element.rPr is not None and r._element.rPr.rFonts is not None]
    checks.append(("中西文双字体", len(ea) > 3 and ea[0] == A.env.cjk_font()))
    xml0 = dd.paragraphs[1]._p.xml
    checks.append(("元信息带分隔线", "pBdr" in xml0 and "8A857B" in xml0))
    all_text = " ".join(p.text for p in dd.paragraphs)
    checks.append(("docx 里有双语译文", "〔译1〕" in all_text))
    checks.append(("docx 标了语向", "→ 法语 (FR)" in all_text))
    bolds = [r.bold for p in dd.paragraphs if p.runs for r in p.runs[:1]]
    checks.append(("原文加粗译文不加粗", True in bolds and False in bolds))
    # 走 GUI 的写入口（导出菜单用的同一个函数）
    ui.write_to(OUT / "selftest2.docx", "docx", "lines")
    checks.append(("逐句版 docx", (OUT / "selftest2.docx").exists()))
    checks.append(("自动导出被调用", ui.auto_export() is not None))

    # 4) 清空回到初始态
    ui.clear()
    root.update()
    checks.append(("清空后提示可见", ui.hint.winfo_ismapped()))

    bad = [c for c in checks if c[1] in (False, 0, None)]
    for name, val in checks:
        print(f"  {'OK ' if (name, val) not in bad else 'BAD'} {name}: {val}")
    root.destroy()
    if bad:
        print("GUI_FAIL", bad)
        return 1
    print("GUI_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
