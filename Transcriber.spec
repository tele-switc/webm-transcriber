# -*- mode: python ; coding: utf-8 -*-
"""跨平台打包配置（Windows / macOS / Linux 共用一份）。

用法：pyinstaller Transcriber.spec
产物：dist/Transcriber/（Win、Linux）或 dist/Transcriber.app（macOS）
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

# 图标：Windows 用 .ico，macOS 用 CI 里由 png 生成的 .icns
ico = Path("installer/icon.ico")
icns = Path("installer/icon.icns")
ICON = str(icns) if sys.platform == "darwin" and icns.exists() else (
    str(ico) if ico.exists() else None)

datas, binaries, hiddenimports = [], [], []
# 只 collect 需要带数据文件的包；huggingface_hub/tokenizers 交给 PyInstaller 自带 hook，
# 否则会把 transformers 这类根本用不到的巨型依赖拖进来。
# onnxruntime 必须带上：faster-whisper 的 VAD 静音过滤靠它，缺了就报 ModuleNotFoundError。
for pkg in ("tkinterdnd2", "faster_whisper", "ctranslate2", "av", "docx", "numpy",
            "onnxruntime", "sentencepiece"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:  # 某平台上装不到就跳过
        print(f"[spec] skip {pkg}: {e}")

# huggingface_hub 运行时要读自身版本元数据，漏了会直接 import 失败
for pkg in ("faster_whisper", "huggingface_hub", "tokenizers", "av"):
    try:
        datas += copy_metadata(pkg)
    except Exception as e:
        print(f"[spec] no metadata for {pkg}: {e}")

excludes = [
    "torch", "sklearn", "scipy", "pandas", "matplotlib", "IPython", "notebook",
    "PIL", "numba", "llvmlite", "pytest", "PyQt5", "PySide6",
    "tkinter.test", "setuptools", "pip", "cv2", "imageio", "soundfile",
    "transformers", "tensorflow", "keras", "jax", "flax", "datasets", "pyarrow",
    "bitsandbytes",
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=excludes,
    noarchive=False,
)

# 开发机上 pip 装的 onnxruntime/ctranslate2 会把 GPU 运行库一起拽进来：
# torch 504MB、onnxruntime CUDA provider 176MB 之类，对 CPU 推理毫无用处。
# excludes 只管 Python 模块，二进制得在这里按路径名剔掉。
DROP_KEYS = ("torch", "providers_cuda", "providers_tensorrt", "providers_dml",
             "providers_coreml", "cublas", "cudnn", "botocore", "s3transfer")


def _keep(item):
    path = f"{item[0]} {item[1]}".lower()
    return not any(k in path for k in DROP_KEYS)


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]
print(f"[spec] kept binaries={len(a.binaries)} datas={len(a.datas)}")  # 必须 ASCII：Windows runner 用 charmap 输出

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Transcriber",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=ICON,
    # 不声明 PerMonitorV2 的话，PyInstaller 生成的 exe 在高分屏上会被系统位图拉伸发虚
    manifest="installer/app.manifest" if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Transcriber")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Transcriber.app",
        icon=ICON,
        bundle_identifier="local.webm.transcriber",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "1.0.0",
            "NSDocumentsFolderUsageDescription": "读取要转写的音视频文件",
        },
    )
