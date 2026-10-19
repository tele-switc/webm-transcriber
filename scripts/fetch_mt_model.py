"""拉取离线翻译模型：CT2 int8 权重 + NLLB 的 sentencepiece 分词器。

两个文件都来自非 gated 的公开仓库，所以不需要任何 HuggingFace token。
跑法：python scripts/fetch_mt_model.py
"""

from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# 重定向到文件时 Windows 控制台是 GBK，中文与勾号都会炸
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import translate as MT  # noqa: E402

# CT2 格式的 int8 权重（4 个文件）+ 另一家镜像里的 spm 分词器
CT2_REPO = "https://huggingface.co/next-social/nllb-200-distilled-600M-int8/resolve/main/"
CT2_FILES = ["config.json", "model.bin", "shared_vocabulary.txt"]
SPM_URL = "https://huggingface.co/Xenova/nllb-200-distilled-600M/resolve/main/sentencepiece.bpe.model"
PROXY = "http://127.0.0.1:7890"


def fetch(url: str, dst: Path, tries: int = 5) -> None:
    """带重试与进度的下载（这台机器到 HF 会间歇性断）。"""
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "w2t-mt"})
            with opener.open(req, timeout=1800) as r:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                tmp = dst.with_suffix(dst.suffix + ".part")
                with open(tmp, "wb") as f:
                    while True:
                        buf = r.read(1 << 20)
                        if not buf:
                            break
                        f.write(buf)
                        got += len(buf)
                        if total and got % (20 << 20) < (1 << 20):
                            print(f"    {got / 1e6:6.0f}/{total / 1e6:.0f}MB "
                                  f"({got / total * 100:.0f}%)", flush=True)
                # 连接被掐断时 read() 只会返回空，不当成错误校验就会留下半截文件
                if total and got < total:
                    raise IOError(f"只收到 {got}/{total} 字节")
                if dst.exists():
                    dst.unlink()
                tmp.replace(dst)
            ok = f"  [ok] {dst.name} {dst.stat().st_size / 1e6:.1f}MB"
        except Exception as e:
            print(f"  重试 {i + 1}: {type(e).__name__} {str(e)[:80]}", flush=True)
            time.sleep(3 + 3 * i)
            continue
        print(ok, flush=True)
        return
    raise RuntimeError(f"下载失败：{url}")


def main() -> int:
    d = MT.env.data_dir() / "models" / MT.MODEL_NAME
    d.mkdir(parents=True, exist_ok=True)
    print(f"目标目录 {d}")
    for name in CT2_FILES:
        if (d / name).exists() and (d / name).stat().st_size > 100:
            print(f"  跳过已有 {name}")
            continue
        print(f"  取 {name}")
        fetch(CT2_REPO + name, d / name)
    if not MT._spm(d).exists():
        print("  取 sentencepiece.bpe.model")
        fetch(SPM_URL, d / "sentencepiece.bpe.model")
    print("模型齐了吗:", MT.has_model())
    return 0 if MT.has_model() else 1


if __name__ == "__main__":
    sys.exit(main())
