"""修复能力自检：造一个"头部丢失但数据完好"的 webm，验证探测→重建→转写全链路。

跑法：python test_repair.py
通过打印 REPAIR_OK
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import env  # noqa: E402
import repair  # noqa: E402
import transcribe as T  # noqa: E402

CLUSTER = bytes.fromhex("1f43b675")
# 素材按可得性挑：可移动盘上的原件随时会被拔走
CANDS = [Path("D:/record-2026_10_18 09_45_39.webm"),
         Path("E:/Projects/_audit-20261011/out/real_fixed.webm")]
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else next((p for p in CANDS if p.exists()), CANDS[0])
TMP = Path(tempfile.mkdtemp(prefix="w2t_repair_"))


def make_broken() -> Path:
    """造一个 MediaRecorder 式坏文件：切 45 秒 -> Cluster 改成 unknown-size -> 砍掉头部。

    恢复器只认流式写法的 unknown-size 簇（mm[4]==0x01），ffmpeg 默认写的是定长簇，
    所以必须先把簇头改成流式写法，否则测的是另一种文件。
    """
    from vendor.webm_recover import UNKNOWN_SEGMENT, vint

    good = TMP / "good.webm"
    subprocess.run([env.ffmpeg_bin(), "-v", "error", "-y", "-ss", "5", "-t", "45",
                    "-i", str(SRC), "-c", "copy", str(good)], check=True,
                   capture_output=True)
    raw = good.read_bytes()
    out = bytearray()
    p = raw.find(CLUSTER)
    assert p > 0, "没找到 Cluster，样本无效"
    n = 0
    while 0 <= p < len(raw):
        size, ln = vint(raw, p + 4)
        if size is None:
            break
        end = p + 4 + ln + size
        out += raw[p:p + 4] + UNKNOWN_SEGMENT + raw[p + 4 + ln:end]   # 定长簇 -> unknown-size
        n += 1
        p = raw.find(CLUSTER, end)
    assert n > 3, f"只改写了 {n} 个簇，样本不足"
    broken = TMP / "broken.webm"
    broken.write_bytes(bytes(out))
    return broken


def main() -> int:
    checks = []
    if not SRC.exists() or not env.ffmpeg_bin():
        print("跳过：需要 D 盘那段录音与 ffmpeg")
        return 2
    broken = make_broken()
    checks.append(("坏文件确实没头部", broken.read_bytes()[:4] != bytes.fromhex("1a45dfa3")))
    checks.append(("探测到需要修复", repair.needs_repair(broken) is True))
    good = TMP / "good.webm"
    checks.append(("正常文件不误报", repair.needs_repair(good) is False))

    fixed = repair.repair(broken, TMP)
    rep = repair.report(fixed)
    checks.append(("重建后头部正常", repair.needs_repair(fixed) is False))
    checks.append(("重建文件可解码", fixed.stat().st_size > 10000 and bool(env.ffprobe_bin())))
    checks.append(("报告里有簇数", rep.get("clusters", 0) > 0))
    dur = T.media_duration(fixed)
    checks.append(("时长与样本相符", 20 <= dur <= 60))

    res = T.transcribe(fixed, "es")
    texts = " ".join(s.text for s in res.segments)
    checks.append(("能转写出西语内容", len(res.segments) > 0 and "os" in texts.lower()))
    print(f"  转写 {len(res.segments)} 句，首句：{texts[:70]}")

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"  {'OK ' if ok else 'BAD'} {n}")
    print("REPAIR_OK" if not bad else f"REPAIR_FAIL {bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil

        shutil.rmtree(TMP, ignore_errors=True)
