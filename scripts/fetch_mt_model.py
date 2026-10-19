"""把 gated 的 NLLB-200 转成 int8 CTranslate2 模型并装进本机模型目录。

需要一次性准备（都在浏览器里做）：
  1. 登录 huggingface.co，打开 https://huggingface.co/facebook/nllb-200-distilled-600M
     点 *Agree and Access*（不点会一直 401）
  2. 在 https://huggingface.co/settings/tokens/new?scopes=read 建一个 Read token

然后：
    HF_TOKEN=hf_xxx python scripts/fetch_mt_model.py

之后 translate.py 会自动走 NLLB 直翻（比 Marian 两跳好一档），
并把模型目录打包成 zip 传 Release 用：python scripts/fetch_mt_model.py --zip-upload
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import translate as MT  # noqa: E402

REPO = "facebook/nllb-200-distilled-600M"
PROXY = os.environ.get("W2T_PROXY", "http://127.0.0.1:7890")
COPY = ["sentencepiece.bpe.model", "tokenizer.json", "tokenizer_config.json",
        "special_tokens_map.json", "config.json", "generation_config.json"]


def convert(work: Path) -> Path:
    """下载（带 token）+ 转 int8 CT2，输出到本机模型目录。"""
    token = os.environ.get("HF_TOKEN", "")
    if not token:
        raise RuntimeError("没给 HF_TOKEN：先按脚本顶部说明去 HF 同意条款并建 Read token")
    os.environ["HF_TOKEN"] = token
    os.environ["HUGGING_FACE_HUB_TOKEN"] = token
    os.environ.setdefault("HTTPS_PROXY", PROXY)
    os.environ.setdefault("HTTP_PROXY", PROXY)

    raw = work / "nllb-raw"
    dst = MT.env.data_dir() / "models" / MT.MODEL_NAME
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(dst, ignore_errors=True)
    conv = shutil.which("ct2-transformers-converter")
    if not conv:
        raise RuntimeError("找不到 ct2-transformers-converter，先 pip install ctranslate2")
    cmd = [conv, "--model", REPO, "--output_dir", str(dst), "--quantization", "int8",
           "--copy_files", *COPY]
    print("转换中（要先下 2.4GB fp32 权重，代理慢时多跑几次）：\n  " + " ".join(cmd))
    for i in range(3):
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        if p.returncode == 0 and (dst / "model.bin").exists():
            print("转换完成 ->", dst)
            return dst
        tail = (p.stderr or p.stdout or "")[-500:]
        print(f"第 {i + 1} 次失败：\n{tail}")
        if "401" in tail or "gated" in tail.lower() or "Unauthorized" in tail:
            raise RuntimeError("HF 仍拒绝访问：说明账号还没在该模型页点 Agree and Access")
        time.sleep(8)
    raise RuntimeError("转换失败，见上面的输出")


def pack(dst: Path) -> Path:
    """打包成 zip，便于传到 Release 供别人首次下载。"""
    zip_path = dst.parent / f"{MT.MODEL_NAME}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in dst.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(dst.parent))
    print(f"zip -> {zip_path}  {zip_path.stat().st_size / 1e6:.0f}MB")
    return zip_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip-upload", action="store_true", help="顺便传到 GitHub Release")
    a = ap.parse_args()
    work = Path(os.environ.get("W2T_HOME", str(MT.env.data_dir()))) / "_build"
    work.mkdir(parents=True, exist_ok=True)
    dst = convert(work)
    print("模型可用了吗:", MT.has_model())
    zip_path = pack(dst)
    if a.zip_upload:
        print("上传请跑：python scripts/build_mt_model.py --upload-only "
              "(需要 GH_PAT，见该脚本)")
    print("\n下一步：python scripts/mt_check.py 6   看真实翻译质量")
    return 0 if MT.has_model() else 1


if __name__ == "__main__":
    sys.exit(main())
