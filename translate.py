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
    for name in ("sentencepiece.bpe.model", "spm.model", "target.spm", "source.spm"):
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


class Hop:
    """一跳翻译：一个 CT2 模型 + 它自己的分词器。

    NLLB 是"一个模型打所有语向"，要在 token 前面加语言码；
    Marian 是"一个语向一个模型"，不需要前缀。两种都支持。
    """

    def __init__(self, kind: str, src: str, tgt: str):
        self.kind, self.src, self.tgt = kind, src, tgt
        self._pair = None

    def dir(self) -> Path:
        return model_dir() if self.kind == "nllb" else marian_dir(self.src, self.tgt)

    def _load(self):
        if self._pair:
            return self._pair
        import ctranslate2
        import sentencepiece as spm

        d = self.dir()
        enc = spm.SentencePieceProcessor()
        enc.Load(str(_spm(d)))
        # Marian 的 source.spm / target.spm 是两个不同词表：
        # 编码用源语言那份，解码必须换目标语言那份，否则解出来是重复乱码
        tgt_spm = d / "target.spm"
        if tgt_spm.exists():
            dec = spm.SentencePieceProcessor()
            dec.Load(str(tgt_spm))
        else:
            dec = enc
        env.prep_cuda_paths()
        # 语言码不在词表里时，模型不会报错，只会吐一堆乱码 —— 必须提前校验
        if self.kind == "nllb":
            vocab = d / "shared_vocabulary.json"
            if vocab.exists():
                import json

                known = set(json.loads(vocab.read_text(encoding="utf-8")))
                for code in (LG.nllb(self.src), LG.nllb(self.tgt)):
                    if code not in known:
                        raise RuntimeError(
                            f"模型词表里没有语言码 {code}（{LG.label(self.src if code == LG.nllb(self.src) else self.tgt)}）")
        self._pair = (enc, dec, ctranslate2.Translator(str(d), compute_type="int8"))
        return self._pair

    def run(self, texts: list[str]) -> list[str]:
        enc, dec, model = self._load()
        if self.kind == "nllb":
            # NLLB 的 CT2 用法：源语言码前置在 source 里，目标语言码走 target_prefix。
            # 两个码都塞进 source 会让解码器乱吐语言标记。
            src = [[LG.nllb(self.src)] + enc.encode(t, out_type=str) for t in texts]
            pre = [[LG.nllb(self.tgt)]] * len(texts)
            hyp = model.translate_batch(src, target_prefix=pre, beam_size=4,
                                        num_hypotheses=1, repetition_penalty=1.3,
                                        max_decoding_length=400)
        else:
            src = [enc.encode(t, out_type=str) for t in texts]
            # 课堂口语没有标点、句子又长，Marian 极易陷入重复循环，必须开重复惩罚
            hyp = model.translate_batch(src, beam_size=2, num_hypotheses=1,
                                        repetition_penalty=1.6, no_repeat_ngram_size=3,
                                        max_decoding_length=320)
        return [dec.decode(h.hypotheses[0]).strip() for h in hyp]


def marian_dir(src: str, tgt: str) -> Path:
    return env.data_dir() / "models" / f"opus-{src}-{tgt}-ct2"


def marian_ready(src: str, tgt: str) -> bool:
    d = marian_dir(src, tgt)
    return (d / "model.bin").exists() and _spm(d).exists()


def plan(src: str, tgt: str) -> list[Hop]:
    """按可用模型规划语向：NLLB 直翻 > Marian 直翻 > Marian 经英语两跳。"""
    if src == tgt:
        return []
    if has_model():
        return [Hop("nllb", src, tgt)]
    if marian_ready(src, tgt):
        return [Hop("marian", src, tgt)]
    if src != "en" and tgt != "en" and marian_ready(src, "en") and marian_ready("en", tgt):
        return [Hop("marian", src, "en"), Hop("marian", "en", tgt)]
    raise RuntimeError(
        f"这台机器上还没有 {LG.label(src)}→{LG.label(tgt)} 的离线翻译模型")


class Translator:
    """一段进一段出的翻译器；模型只加载一次。"""

    def __init__(self, src: str = "es", tgt: str = "zh"):
        self.src_code, self.tgt_code = src[:2], tgt[:2]
        LG.nllb(self.src_code), LG.nllb(self.tgt_code)   # 早失败：语向不在表里就别浪费时间
        self.hops = plan(self.src_code, self.tgt_code)

    def translate(self, texts, on_progress=None, should_stop=None) -> list[str]:
        """逐跳翻译整批文本；on_progress(已完成段数, 总段数)。"""
        cur = list(texts)
        total = len(cur)
        for hop in self.hops:
            out: list[str] = []
            for i in range(0, total, 16):
                if should_stop and should_stop():
                    return out
                out += hop.run(cur[i:i + 16])
                if on_progress and len(self.hops) == 1:
                    on_progress(min(i + 16, total), total)
            cur = out
        if on_progress:
            on_progress(total, total)
        return cur


def translate_pairs(pairs, src: str, tgt: str = "zh", on_progress=None,
                    on_note=None, should_stop=None) -> list[str]:
    """给 Result.paired() 的 (起, 止, 原文, 旧译文) 补译文；只翻原文列。"""
    if on_note and not (has_model() or marian_ready(src[:2], tgt[:2])):
        on_note("准备离线翻译模型…")
    tr = Translator(src, tgt)
    return tr.translate([p[2] for p in pairs], on_progress=on_progress,
                        should_stop=should_stop)
