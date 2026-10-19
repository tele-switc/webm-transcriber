"""真跑一遍离线翻译：用这次录音的真实段落，看 NLLB int8 的中文质量与耗时。

跑法：python scripts/mt_check.py [段数] [--tgt fr]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import translate as MT  # noqa: E402
import reexport as R  # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    n = int(args[0]) if args else 8
    tgt = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--tgt=")), "zh")
    srt = ROOT / "output" / "record-2026_10_18 09_45_39.srt"
    if not srt.exists():
        print("缺少 output/*.srt，先用 reexport.py 指向任一 srt")
        return 2
    res = R.load(srt)
    by_sent = "--sentences" in sys.argv
    items = ([("", "", s.text) for s in res.segments[:n]] if by_sent
             else [(a, b, t) for a, b, t, _ in res.paired()][:n])
    src = (res.language or "es")[:2]
    print(f"{'逐句' if by_sent else '逐段'} · 语向 {src}→{tgt} · 模型 {MT.model_dir()}")
    tr = MT.Translator(src, tgt)
    t0 = time.time()
    out = tr.translate([i[2] for i in items])
    dt = time.time() - t0
    print(f"翻译 {len(out)} 条耗时 {dt:.1f}s（均 {dt / max(len(out), 1):.1f}s/条）\n")
    for (a, b, text), hyp in zip(items, out):
        print(f"ES: {text[:96]}")
        print(f"{tgt.upper()}: {hyp[:96]}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
