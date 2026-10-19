"""语言表：转写（whisper）与翻译（NLLB）共用一份代码，界面上只认中文名。

whisper 支持近百种语言，NLLB-200 有 200 种；这里取两者都覆盖、且实际有用的 24 种，
避免界面上出现"能转写但翻不了"的语言。
"""

from __future__ import annotations

# (ISO-639-1, 中文名, NLLB 码)
LANGS = [
    ("es", "西班牙语", "spa_Latn"),
    ("zh", "简体中文", "zho_Hans"),
    ("en", "英语", "eng_Latn"),
    ("ja", "日语", "jpn_Jpan"),
    ("ko", "韩语", "kor_Hang"),
    ("fr", "法语", "fra_Latn"),
    ("de", "德语", "deu_Latn"),
    ("pt", "葡萄牙语", "por_Latn"),
    ("it", "意大利语", "ita_Latn"),
    ("ru", "俄语", "rus_Cyrl"),
    ("ar", "阿拉伯语", "arb_Arab"),
    ("nl", "荷兰语", "nld_Latn"),
    ("pl", "波兰语", "pol_Latn"),
    ("tr", "土耳其语", "tur_Latn"),
    ("sv", "瑞典语", "swe_Latn"),
    ("da", "丹麦语", "dan_Latn"),
    ("fi", "芬兰语", "fin_Latn"),
    ("el", "希腊语", "ell_Grek"),
    ("he", "希伯来语", "heb_Hebr"),
    ("hi", "印地语", "hin_Deva"),
    ("th", "泰语", "tha_Thai"),
    ("vi", "越南语", "vie_Latn"),
    ("id", "印度尼西亚语", "ind_Latn"),
    ("uk", "乌克兰语", "ukr_Cyrl"),
]

BY_CODE = {c: (zh, nllb) for c, zh, nllb in LANGS}
NLLB = {c: nllb for c, _, nllb in LANGS}
LABELS = {c: zh for c, zh, _ in LANGS}
AUTO = "auto"


def label(code: str) -> str:
    """界面/文档里显示的语言名；未知代码原样返回。"""
    if not code:
        return "未知"
    return LABELS.get(code[:2].lower(), code)


def nllb(code: str) -> str:
    """转成 NLLB 的 triletter 码；不在表里就报错，避免静默翻错。"""
    key = (code or "")[:2].lower()
    if key not in NLLB:
        raise RuntimeError(f"暂不支持翻译 {code or '(未知)'}；可选：{'、'.join(LABELS.values())}")
    return NLLB[key]


def is_supported(code: str) -> bool:
    return (code or "")[:2].lower() in NLLB


def choices() -> list[str]:
    """下拉框用的中文名列表（顺序即表顺序）。"""
    return list(LABELS.values())


def code_of(label_text: str) -> str:
    """中文名反查代码；找不到返回空串。"""
    for c, zh, _ in LANGS:
        if zh == label_text:
            return c
    return ""
