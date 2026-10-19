"""界面截图自检：把真实转写结果渲染进窗口并抓屏，用于肉眼检查排版。

跑法：python shot.py [要显示的txt]    产物 output/ui_preview.png
"""

import sys
import time
import ctypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import app as A  # noqa: E402
import transcribe as T  # noqa: E402

HERE = Path(__file__).parent
SHOT = HERE / "output" / "ui_preview.png"
TXT = Path(sys.argv[1]) if len(sys.argv) > 1 else None


def main():
    root = A.TkinterDnD.Tk()
    ui = A.App(root)
    if TXT and TXT.name == "idle":
        """只截初始拖放页。"""
        root.geometry("+0+0")
        root.attributes("-topmost", True)
        root.focus_force()
        for _ in range(10):
            root.update_idletasks()
            root.update()
            time.sleep(0.04)
        time.sleep(0.3)
        root.update()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        import ctypes.wintypes as wt

        r = wt.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
        from PIL import ImageGrab

        SHOT.parent.mkdir(exist_ok=True)
        ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True
                       ).save(HERE / "output" / "ui_idle.png")
        print("saved idle", r.left, r.top, r.right, r.bottom)
        root.destroy()
        return 0
    # 直接渲染一屏真实内容（不走 GPU）
    segs = []
    if TXT and TXT.exists():
        for i, line in enumerate(TXT.read_text(encoding="utf-8").splitlines()):
            if line.strip():
                segs.append(T.Segment(i * 12.0, i * 12.0 + 11.0, line.strip()))
    if not segs:
        segs = [T.Segment(0, 8, "（示例）Buenas, hoy vamos a practicar la comprensión lectora.")]
    ui.result = T.Result(source=Path("record-2026_10_18 09_45_39.webm"), language="es",
                         duration=4472.0, segments=segs, engine="local large-v3-turbo")
    ui.show_text_area()
    ui.set_title(ui.result.source.name)
    ui.set_status(f"完成 · {len(segs)} 句 · 西班牙语 (ES) · 时长 {T.fmt_hms(ui.result.duration)}"
                  " · 已存 录音 2026-10-18 09:45.docx")
    for s in segs[:60]:
        ui.append_seg(s)
    root.geometry("+0+0")
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    for _ in range(12):
        root.update_idletasks()
        root.update()
        time.sleep(0.04)
    ui.bar.coords(ui._bar_fg, 0, 0, ui.bar.winfo_width(), 2)
    for _ in range(12):
        root.update_idletasks()
        root.update()
        time.sleep(0.04)
    root.after(200, root.update)
    time.sleep(0.35)
    root.update()
    for name in ("top", "mid", "bot"):
        w = getattr(ui, name)
        print(f"{name}: y={w.winfo_y()} h={w.winfo_height()} mapped={w.winfo_ismapped()}")
    print("win:", root.winfo_height(), "text h:", ui.text.winfo_height())

    # 用 Win32 物理矩形抓屏，避开 DPI 换算坑
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
    import ctypes.wintypes as wt

    r = wt.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
    print("window rect:", r.left, r.top, r.right, r.bottom)
    print("root client:", root.winfo_rootx(), root.winfo_rooty(),
          "bot screen:", ui.bot.winfo_rootx(), ui.bot.winfo_rooty(), ui.bot.winfo_height())
    try:
        from PIL import ImageGrab

        img = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
        SHOT.parent.mkdir(exist_ok=True)
        img.save(SHOT)
        bx, by = ui.bot.winfo_rootx(), ui.bot.winfo_rooty()
        ImageGrab.grab(bbox=(bx - 6, by - 6, bx + ui.bot.winfo_width() + 6,
                             by + ui.bot.winfo_height() + 6), all_screens=True
                       ).save(HERE / "output" / "ui_bottom.png")
        px = list(img.convert("L").getdata())[::5000]
        print("saved", SHOT, img.size, "bright_samples", sum(px) // max(len(px), 1))
    except Exception as e:
        print("grab_failed", type(e).__name__, e)
    root.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
