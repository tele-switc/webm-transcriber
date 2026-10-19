"""从已有 srt/json 重新排版导出，不必重跑转录。

用法：
  python reexport.py 某.srt            # 出 blocks 版 docx
  python reexport.py 某.srt --mode=lines
  python reexport.py 某.srt --html     # 顺带出一份同排版 HTML，便于肉眼检查
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import docx_export as D
from transcribe import Result, Segment


def load(path: Path) -> Result:
    """解析 srt 或 json 成 Result。"""
    txt = path.read_text(encoding="utf-8-sig")
    stem = re.sub(r"\.(srt|json|txt)$", "", path.name, flags=re.I)
    if path.suffix.lower() == ".json":
        d = json.loads(txt)
        res = Result(source=Path(d.get("source", stem)), language=d.get("language", "?"),
                     duration=d.get("duration", 0.0), engine=d.get("engine", ""))
        res.segments = [Segment(s["start"], s["end"], s["text"]) for s in d["segments"]]
        return res
    res = Result(source=Path(stem + ".webm"), language="?", duration=0.0, engine="")
    for blk in re.finditer(r"(\d+)\s*\n(\d\d):(\d\d):(\d\d)[,.](\d+)\s*-->\s*"
                           r"(\d\d):(\d\d):(\d\d)[,.](\d+)\s*\n(.*?)(?=\n\s*\n|\Z)",
                           txt, re.S):
        g = blk.groups()
        st = int(g[1]) * 3600 + int(g[2]) * 60 + int(g[3]) + int(g[4]) / 1000
        en = int(g[5]) * 3600 + int(g[6]) * 60 + int(g[7]) + int(g[8]) / 1000
        res.segments.append(Segment(st, en, g[9].strip().replace("\n", " ")))
    if res.segments:
        res.duration = res.segments[-1].end
    _fill_meta_from_md(res, path)
    return res


def _fill_meta_from_md(res: Result, path: Path) -> None:
    """同名 .md 头部带着语言/时长/引擎，补回来免得文档写 auto。"""
    md = path.with_suffix(".md")
    if not md.exists():
        return
    head = md.read_text(encoding="utf-8")[:600]
    for pat, attr in ((r"语言:\s*(\S+)", "language"), (r"引擎:\s*(.+)", "engine")):
        m = re.search(pat, head)
        if m:
            setattr(res, attr, m.group(1).strip())
    m = re.search(r"时长:\s*(\d+):(\d+):(\d+)", head)
    if m:
        res.duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def html(res: Result, path: Path, mode: str) -> Path:
    """同排版规则的 HTML 预览，用来肉眼检查分段节奏。"""
    rows = []
    if mode == "lines":
        for s in res.segments:
            if s.text:
                rows.append(f'<p class="line"><span class="t">{D.hms(s.start)}</span>'
                            f'{D.tidy(s.text)}</p>')
    else:
        for a, b, t in D.group(res.segments):
            rows.append(f'<p class="lab">{D.hms(a)} – {D.hms(b)}</p>'
                        f'<p class="body">{D.tidy(t)}</p>')
    meta = "  ·  ".join([f"语言 {D.lang_name(res.language)}", f"时长 {D.hms(res.duration)}",
                         f"{len(res.segments)} 句", D.short_engine(res.engine)])
    path.write_text(f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<style>
@page {{ size: A4; margin: 22mm 26mm; }}
body {{ background:#e8e4dc; margin:0; }}
.page {{ background:#fff; width:21cm; min-height:29.7cm; margin:18px auto;
  padding:2.2cm 2.6cm; box-sizing:border-box; font-family:Georgia,'Microsoft YaHei UI',serif;
  color:#252422; font-size:11pt; line-height:1.34; text-align:justify; }}
h1 {{ font-size:17pt; margin:0 0 2px; }}
.meta {{ font-size:9pt; color:#8A857B; border-bottom:1px solid #D9D3C7; padding-bottom:8px;
  margin-bottom:14px; }}
.lab {{ font-size:8.5pt; color:#B8B2A6; margin:14px 0 1px; text-align:left; }}
.body {{ margin:0 0 7px; }}
.line {{ margin:0 0 3px; font-size:10.5pt; text-align:left; }}
.line .t {{ color:#B8B2A6; font-size:8.5pt; margin-right:8px; }}
</style></head><body><div class="page"><h1>{D.pretty_title(res.source.name)}</h1>
<div class="meta">{meta}</div>{''.join(rows)}</div></body></html>""", encoding="utf-8")
    return path


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    mode = next((a.split("=", 1)[1] for a in argv[1:] if a.startswith("--mode=")), "blocks")
    if not args:
        print(__doc__)
        return 2
    src = Path(args[0])
    res = load(src)
    out = src.with_name(src.stem + (".逐句版" if mode == "lines" else "") + ".docx")
    D.save(res, out, mode=mode)
    print("docx ->", out, f"({out.stat().st_size} B)  mode={mode}  块数",
          len(D.group(res.segments)) if mode == "blocks" else len(res.segments))
    if "--html" in argv:
        h = html(res, src.with_suffix(".preview.html"), mode)
        print("html ->", h)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
