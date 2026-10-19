"""把 gated 的 NLLB-200-distilled-600M 转成 int8 CTranslate2 模型并传到 GitHub Release。

跑之前需要两样东西：
  1. 在 https://huggingface.co/facebook/nllb-200-distilled-600M 点 Agree and Access
  2. 环境变量 HF_TOKEN（只读即可）与 GH_PAT（要有上传 Release 附件的权限）

用法：python scripts/build_mt_model.py [--out DIR]
产物：nllb-600m-ct2/ 目录 + 同名 zip，并自动挂到 models-nllb-600m-ct2 这个 tag 的 Release。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ID = "facebook/nllb-200-distilled-600M"
NAME = "nllb-600m-ct2"
TAG = f"models-{NAME}"
GITHUB_REPO = os.environ.get("GH_REPO", "tele-switc/webm-transcriber")
COPY = ["sentencepiece.bpe.model", "tokenizer.json", "tokenizer_config.json",
        "special_tokens_map.json", "config.json", "generation_config.json"]


def convert(out: Path) -> Path:
    """调 ct2-transformers-converter 做 int8 量化转换。"""
    dst = out / NAME
    cmd = [sys.executable, "-m", "ctranslate2.converters.transformers_converter",
           "--model", REPO_ID, "--output_dir", str(dst), "--quantization", "int8",
           "--copy_files", *COPY]
    env = dict(os.environ)
    if os.environ.get("HF_TOKEN"):
        env["HUGGING_FACE_HUB_TOKEN"] = os.environ["HF_TOKEN"]
    print("转换中（要先把 2.4GB 权重下下来，代理不稳时多试几次）：\n  " + " ".join(cmd))
    subprocess.run(cmd, check=True, env=env)
    if not (dst / "model.bin").exists():
        raise RuntimeError(f"转换没产出 model.bin：{dst}")
    return dst


def pack(dst: Path) -> Path:
    """压成 zip（顶层就是模型目录名，解压即用）。"""
    zip_path = dst.parent / f"{NAME}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in dst.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(dst.parent))
    print(f"打包 {zip_path} = {zip_path.stat().st_size / 1e6:.0f}MB")
    return zip_path


def upload(zip_path: Path) -> str:
    """建（或复用）tag 的 Release 并传附件。"""
    import json
    import urllib.request

    tok = os.environ.get("GH_PAT", "")
    if not tok:
        print("没设 GH_PAT，跳过上传。可手动把 zip 拖到 Release 页面。")
        return ""

    def api(path, method="GET", payload=None, headers=None):
        data = json.dumps(payload).encode() if payload else None
        req = urllib.request.Request(f"https://api.github.com{path}", data=data, method=method,
                                     headers={"Authorization": f"Bearer {tok}",
                                              "Accept": "application/vnd.github+json",
                                              "User-Agent": "w2t-build", **(headers or {})})
        proxy = {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(proxy))
        return json.loads(opener.open(req, timeout=300).read().decode())

    try:
        rel = api(f"/repos/{GITHUB_REPO}/releases/tags/{TAG}")
    except Exception:
        rel = api(f"/repos/{GITHUB_REPO}/releases", "POST",
                  {"tag_name": TAG, "name": f"离线翻译模型 {NAME}", "body":
                   "int8 量化的 NLLB-200-distilled-600M，供拖拽转录台首次翻译时下载。",
                   "draft": False, "prerelease": False})
    up = rel["upload_url"].split("{")[0] + f"?name={zip_path.name}"
    raw = zip_path.read_bytes()
    req = urllib.request.Request(up, data=raw, method="POST", headers={
        "Authorization": f"Bearer {tok}", "Content-Type": "application/zip",
        "User-Agent": "w2t-build", "Accept": "application/vnd.github+json"})
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": "http://127.0.0.1:7890",
                                     "https": "http://127.0.0.1:7890"}))
    got = json.loads(opener.open(req, timeout=1800).read().decode())
    print("已上传：", got.get("browser_download_url"))
    return got.get("browser_download_url", "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path.home() / ".cache" / "w2t-mt-build"))
    ap.add_argument("--skip-upload", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    dst = convert(out)
    zip_path = pack(dst)
    if not a.skip_upload:
        upload(zip_path)
    print("完成。之后 translate.py 会自动从 Release 拉这个 zip。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
