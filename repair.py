"""坏录像自动修复：探测 MediaRecorder 强杀后丢头部的 webm，并就地重建。

修复算法在 vendor/webm_recover.py（原样保留 CLI 与退出码约定），
这里只负责判断"要不要修"和"修完给谁用"。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import env

EBML_MAGIC = bytes.fromhex("1a45dfa3")   # 正常 Matroska/WebM 文件的第一个元素
CLUSTER_ID = bytes.fromhex("1f43b675")   # 只剩 Cluster 链时的开头特征


def script_path() -> Path:
    return Path(__file__).resolve().parent / "vendor" / "webm_recover.py"


def needs_repair(path: Path) -> bool:
    """开头不是 EBML header 但能找到 Cluster，就是"数据在、目录没了"。"""
    try:
        with open(path, "rb") as f:
            head = f.read(64)
    except OSError:
        return False
    if head[:4] == EBML_MAGIC:
        return False
    return CLUSTER_ID in head[:16]


def repair(path: Path, out_dir: Path | None = None, on_note=None) -> Path:
    """重建头部并输出到「修复后」目录，返回新文件路径。"""
    from vendor import webm_recover as W  # 延迟导入：只有真要修时才加载

    dst_dir = Path(out_dir) if out_dir else path.parent / "修复后"
    dst_dir.mkdir(parents=True, exist_ok=True)
    target = dst_dir / (path.stem + "_修复.webm")
    if on_note:
        on_note("录像头部丢失，正在重建 EBML/Tracks…")
    argv = [str(script_path()), str(path), str(target), "--quiet"]
    ff = env.ffmpeg_bin()
    if ff:
        argv += ["--ffmpeg", ff]   # 用我们解析到的 ffmpeg，避免修复器再按 PATH 找一遍
    saved, sys.argv = sys.argv, argv
    try:
        W.main()
    except SystemExit as e:  # 修复器用退出码表达结果
        if e.code not in (0, None):
            raise RuntimeError(f"修复失败（退出码 {e.code}），详见 {target}.report.json") from e
    finally:
        sys.argv = saved
    if not target.exists():
        raise RuntimeError("修复没有产出文件")
    return target


def report(target: Path) -> dict:
    """读修复报告（簇数、时长等），拿不到就返回空。"""
    try:
        return json.loads(Path(str(target) + ".report.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
