"""离线翻译：CT2 版 NLLB-200-distilled-600M，原文 → 中文（或反向）。

模型不随包分发：首次用到时从 GitHub Release 拉 int8 版（约 600MB）到数据目录。
推理只依赖 ctranslate2 + sentencepiece，都不需要 torch。
"""

from __future__ import annotations

import os
import shutil
import urllib.request
from pathlib import Path

import env
import languages as LG

MODEL_NAME = "nllb-600m-ct2"
# 打包好的 int8 模型；HF 上原始权重是 gated 的，所以走自己的 Release 分发
ASSET = ("https://github.com/tele-switc/webm-transcriber/releases/download/"
         f"models-{MODEL_NAME}/{MODEL_NAME}.zip")


def model_dir() -> Path:
    for cand in (Path(os.environ.get("W2T_MT_DIR", "")), env.data_dir() / "models" / MODEL_NAME,
                 env.bundle_dir() / "models" / MODEL_NAME):
        if cand and (cand / "model.bin").exists() and _spm(cand).exists():
            return cand
    return env.data_dir() / "models" / MODEL_NAME


def _spm(d: Path) -> Path:
    for name in ("sentencepiece.bpe.model", "spm.model"):
        p = d / name
        if p.exists():
            return p
    return d / "sentencepiece.bpe.model"


def has_model() -> bool:
    return (model_dir() / "model.bin").exists() and _spm(model_dir()).exists()


def download(on_note=None) -> Path:
    """下载并解压 int8 模型到数据目录。"""
    import zipfile

    dest = env.data_dir() / "models"
    dest.mkdir(parents=True, exist_ok=True)
    zip_path = dest / f"{MODEL_NAME}.zip"
    if on_note:
        on_note("首次翻译需下载离线翻译模型（约 600MB，只需一次）…")
    req = urllib.request.Request(ASSET, headers={"User-Agent": "webm-transcriber"})
    with urllib.request.urlopen(req, timeout=1800) as r, open(zip_path, "wb") as f:
        shutil.copyfileobj(r, f, 1024 * 1024)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(dest)
    zip_path.unlink(missing_ok=True)
    if not has_model():
        raise RuntimeError(f"翻译模型解压后不完整：{dest / MODEL_NAME}")
    return model_dir()


class Translator:
    """一段进一段出的 NLLB 翻译器；模型只加载一次。"""

    def __init__(self, src: str = "es", tgt: str = "zh"):
        # 语向不支持时 LG.nllb 会直接报错，界面据此退回纯原文
        self.src, self.tgt = LG.nllb(src), LG.nllb(tgt)
        self._model = None
        self._sp = None

    def _load(self):
        if self._model is not None:
            return
        import sentencepiece as spm

        if not has_model():
            download()
        d = model_dir()
        env.prep_cuda_paths()
        import ctranslate2

        self._sp = spm.SentencePieceProcessor()
        self._sp.Load(str(_spm(d)))
        # int8 在 CPU 上就够快，也不逼用户装 CUDA
        self._model = ctranslate2.TranslationModel(str(d), compute_type="int8")

    def translate(self, texts, on_progress=None, should_stop=None) -> list[str]:
        """批量翻译；on_progress(已完成段数, 总段数)。"""
        self._load()
        out: list[str] = []
        batch = 16
        for i in range(0, len(texts), batch):
            if should_stop and should_stop():
                break
            chunk = texts[i:i + batch]
            tok = [[self.src, self.tgt] + self._sp.encode(t, out_type=str) for t in chunk]
            hyp = self._model.translate_batch(tok, beam_size=2, num_hypotheses=1)
            out += [self._sp.decode(h.hypotheses[0]) for h in hyp]
            if on_progress:
                on_progress(min(i + batch, len(texts)), len(texts))
        return out


def translate_pairs(pairs, src: str, tgt: str = "zh", on_progress=None,
                    on_note=None, should_stop=None) -> list[str]:
    """给 Result.paired() 的 (起, 止, 原文, 旧译文) 补译文；只翻原文列。"""
    tr = Translator(src, tgt)
    if on_note and not has_model():
        on_note("准备离线翻译模型…")
    return tr.translate([p[2] for p in pairs], on_progress=on_progress,
                        should_stop=should_stop)
