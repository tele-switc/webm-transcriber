"""跨平台环境适配：数据目录、模型、ffmpeg、CUDA、字体、打开文件。

原则：环境变量优先 → 随包内置 → 平台默认位置 → 本机已有缓存（老用户零成本）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "webm-transcriber"
MODEL_NAME = os.environ.get("W2T_MODEL", "large-v3-turbo")
# 默认用速度/体积平衡的 turbo；想要更准可设 W2T_MODEL=large-v3
REPO_ID = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """PyInstaller 解包后的资源目录（源码运行时就是项目目录）。"""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def data_dir() -> Path:
    """可写的数据目录（放下载的模型）。W2T_HOME 可覆盖。"""
    env = os.environ.get("W2T_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / APP_NAME


def _existing_dirs(*cands: Path | None) -> list[Path]:
    return [p for p in cands if p and Path(p).exists()]


def model_dir() -> Path:
    """返回含 model.bin 的模型目录；都没有时返回下载目标目录。"""
    for p in _model_search():
        if (p / "model.bin").exists():
            return p
    return data_dir() / "models" / MODEL_NAME


def _model_search() -> list[Path]:
    cands = []
    if os.environ.get("W2T_MODEL_DIR"):
        cands.append(Path(os.environ["W2T_MODEL_DIR"]))
    cands.append(bundle_dir() / "models" / MODEL_NAME)      # 随包内置
    cands.append(data_dir() / "models" / MODEL_NAME)        # 首次下载到这里
    # 本机既有缓存：老机器上不必再下 1.6GB
    if sys.platform == "win32":
        cands.append(Path.home() / "caches" / "whisper" / MODEL_NAME)
        cands.append(Path.home() / ".cache" / "whisper" / MODEL_NAME)
    else:
        cands.append(Path.home() / ".cache" / "whisper" / MODEL_NAME)
    return [p for p in cands if p]


def has_model() -> bool:
    return (model_dir() / "model.bin").exists()


def download_model() -> Path:
    """从 HuggingFace 拉模型到数据目录（约 1.6GB，只需一次）。"""
    os.environ.pop("HF_HUB_OFFLINE", None)
    from huggingface_hub import snapshot_download

    dest = data_dir() / "models" / MODEL_NAME
    dest.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=REPO_ID, local_dir=str(dest), max_workers=4)
    if not (dest / "model.bin").exists():
        raise RuntimeError(f"模型下载不完整：{dest}")
    return dest


def cuda_dirs() -> list[Path]:
    """可用的 CUDA/cuDNN 运行库目录（存在才返回）。"""
    cands = []
    if os.environ.get("W2T_CUDA_DIR"):
        cands.append(Path(os.environ["W2T_CUDA_DIR"]))
    cands.append(bundle_dir() / "_cuda")
    if sys.platform == "win32":
        cands.append(Path.home() / "caches" / "ct2-cuda12")
    return _existing_dirs(*cands)


def _exe(name: str) -> str:
    """打包时先找随包二进制，再退回 PATH。"""
    local = bundle_dir() / (name + (".exe" if sys.platform == "win32" else ""))
    if local.exists():
        return str(local)
    found = shutil.which(name)
    return found or ""


def ffmpeg_bin() -> str:
    return os.environ.get("W2T_FFMPEG") or _exe("ffmpeg")


def ffprobe_bin() -> str:
    return os.environ.get("W2T_FFPROBE") or _exe("ffprobe")


def media_tools() -> tuple[str, str]:
    """返回 (ffmpeg, ffprobe)；缺 ffmpeg 时返回空串由上层报错。"""
    return ffmpeg_bin(), ffprobe_bin()


def cjk_font() -> str:
    """各平台都有的中文字体名（docx 与 GUI 共用）。"""
    if sys.platform == "win32":
        return "Microsoft YaHei"
    if sys.platform == "darwin":
        return "PingFang SC"
    return "Noto Sans CJK SC"


def ui_font() -> str:
    if sys.platform == "win32":
        return "Microsoft YaHei UI"
    if sys.platform == "darwin":
        return "PingFang SC"
    return "Noto Sans CJK SC"


def open_path(target: Path) -> None:
    """在资源管理器/Finder 里定位到某个文件或目录。"""
    target = Path(target)
    if sys.platform == "win32":
        if target.is_file():
            subprocess.run(["explorer", "/select,", str(target)], check=False)
        else:
            os.startfile(str(target))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        cmd = ["open", "-R", str(target)] if target.is_file() else ["open", str(target)]
        subprocess.run(cmd, check=False)
    else:
        folder = target if target.is_dir() else target.parent
        subprocess.run(["xdg-open", str(folder)], check=False)


def find_ffmpeg_or_av() -> bool:
    """能不能解码：有 ffmpeg 二进制，或有随 wheel 自带解码库的 PyAV。"""
    return bool(ffmpeg_bin()) or has_pyav()


def has_pyav() -> bool:
    try:
        import av  # noqa: F401

        return True
    except ImportError:
        return False


def gpu_available() -> bool:
    """是否真能吃到 CUDA（库齐 + 有设备）。"""
    try:
        import ctranslate2 as ct2

        return ct2.get_cuda_device_count() > 0
    except Exception:
        return False


def summary() -> str:
    """给界面/日志看的一行环境说明。"""
    ff, _ = media_tools()
    return (f"模型 {model_dir()} · ffmpeg {ff or '未找到'} · "
            f"CUDA 目录 {len(cuda_dirs())} 个 · 数据 {data_dir()}")
