"""转录内核：解码音频 -> faster-whisper GPU 转录 -> 写出 txt / md / srt。

被 GUI（app.py）和命令行共用。中文注释保持简洁。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import env
import repair

# Windows 控制台默认 GBK，西语/中文重音字符会直接崩，统一改 UTF-8
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

MODEL_NAME = env.MODEL_NAME


@dataclass
class Segment:
    """一句话：起止秒 + 文本。"""

    start: float
    end: float
    text: str


@dataclass
class Result:
    """一次转录的产物。"""

    source: Path
    language: str = ""
    duration: float = 0.0
    segments: list[Segment] = field(default_factory=list)
    engine: str = ""
    repaired: bool = False
    translations: list[str] = field(default_factory=list)   # 与 segments 同序，可空

    def paired(self):
        """按停顿聚段后的 (起, 止, 原文, 译文) 列表；没翻译时译文为空串。"""
        import docx_export as D

        out = []
        for i, (a, b, text) in enumerate(D.group(self.segments)):
            tr = ""
            if self.translations and i < len(self.translations):
                tr = self.translations[i]
            out.append((a, b, text, tr))
        return out

    @property
    def plain(self) -> str:
        return "\n".join(s.text for s in self.segments if s.text)

    def markdown(self) -> str:
        lines = [f"# {self.source.name}", ""]
        lines.append(f"- 语言: {self.language}  ")
        lines.append(f"- 时长: {fmt_hms(self.duration)}  ")
        lines.append(f"- 引擎: {self.engine}")
        if self.repaired:
            lines.append("  ")
            lines.append("> 源录像的 WebM 头部丢失，已自动重建 EBML/Info/Tracks 后再转写。")
        lines.append("")
        for s in self.segments:
            if s.text:
                lines.append(f"**[{fmt_ts(s.start)}] {s.text}**")
                lines.append("")
        return "\n".join(lines)

    def srt(self) -> str:
        out = []
        for i, s in enumerate(self.segments, 1):
            if not s.text:
                continue
            out.append(f"{i}\n{srt_ts(s.start)} --> {srt_ts(s.end)}\n{s.text}\n")
        return "\n".join(out)

    def vtt(self) -> str:
        out = ["WEBVTT", ""]
        for s in self.segments:
            if s.text:
                out.append(f"{srt_ts(s.start).replace(',', '.')} --> "
                           f"{srt_ts(s.end).replace(',', '.')}")
                out.append(s.text)
                out.append("")
        return "\n".join(out)

    def json_text(self) -> str:
        import json

        return json.dumps(
            {"source": self.source.name, "language": self.language,
             "duration": round(self.duration, 2), "engine": self.engine,
             "segments": [{"start": s.start, "end": s.end, "text": s.text}
                          for s in self.segments if s.text]},
            ensure_ascii=False, indent=2)


def fmt_hms(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_ts(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def srt_ts(sec: float) -> str:
    ms = int(round((sec - int(sec)) * 1000))
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ---------------- 音频解码 ----------------

def media_duration(path: Path) -> float:
    """用 ffprobe 拿时长；webm 缺索引时靠逐包解码兜底。"""
    ffprobe = env.ffprobe_bin()
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=60,
        ).stdout.strip()
        if out and out.lower() not in ("n/a", "na"):
            return float(out)
    except Exception:
        pass
    # 兜底：容器没有 duration 元数据（浏览器录制的 webm 常见），解到 null 读末尾时间
    if find_ffmpeg():
        try:
            p = subprocess.run(
                [env.ffmpeg_bin(), "-v", "error", "-i", str(path), "-map", "a:0?",
                 "-f", "null", "-"],
                capture_output=True, text=True, timeout=900,
            )
            stamps = re.findall(r"time=(\d+):(\d+):(\d+)\.(\d+)", p.stderr)
            if stamps:
                h, m, s, ms = stamps[-1]
                return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 100
        except Exception:
            pass
    try:  # 再兜底：PyAV 读容器时长
        import av

        with av.open(str(path)) as c:
            return (c.duration or 0) / 1_000_000
    except Exception:
        return 0.0


def wav_duration(wav: Path) -> float:
    """标准库读 wav 时长，不依赖 ffprobe。"""
    try:
        import wave

        with wave.open(str(wav)) as w:
            return w.getnframes() / float(w.getframerate() or 16000)
    except Exception:
        return 0.0


def extract_wav_pyav(path: Path, wav: Path) -> bool:
    """没有 ffmpeg 时的兜底：用 PyAV（wheel 自带解码库）解出 16k 单声道 wav。

    这样 macOS/Linux 的安装包不必再塞一个 ffmpeg 二进制。
    """
    try:
        import av
        import numpy as np
        import wave
    except ImportError:
        return False
    try:
        with av.open(str(path)) as c:
            if not [s for s in c.streams if s.type == "audio"]:
                return False
            res = av.AudioResampler(format="s16", layout="mono", rate=16000)
            frames = [r.to_ndarray() for f in c.decode(audio=0) for r in res.resample(f)]
        if not frames:
            return False
        data = np.concatenate(frames, axis=-1).reshape(-1).astype("<i2")
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(data.tobytes())
        return wav.stat().st_size > 44
    except Exception:
        return False


def extract_wav(path: Path, tmp_dir: Path) -> Path:
    """任意音视频 -> 16 kHz 单声道 wav（whisper 的输入格式）。"""
    wav = tmp_dir / (path.stem[:60].replace(" ", "_") + ".wav")
    if find_ffmpeg():
        cmd = [env.ffmpeg_bin(), "-nostdin", "-v", "error", "-y", "-i", str(path),
               "-vn", "-map", "a:0?", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
               str(wav)]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if p.returncode == 0 and wav.exists() and wav.stat().st_size > 45:
            return wav
        err = (p.stderr or "")[-400:]
    else:
        err = "未装 ffmpeg"
    if extract_wav_pyav(path, wav):
        return wav
    raise RuntimeError(f"没有可解码的音轨（{err}）")


def find_ffmpeg() -> bool:
    return bool(env.ffmpeg_bin())


# ---------------- 模型加载 ----------------

_model = None
_model_info = ""


def _prep_dll_path() -> None:
    """ctranslate2 的 CUDA 运行库必须在 import 前挂好，否则加载失败。"""
    for d in env.cuda_dirs():
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(d))
            except OSError:
                pass


def load_model(device: str = "auto", on_note=None):
    """加载模型：本地已有直接用，没有先下载；GPU 不可用自动回落 CPU。"""
    global _model, _model_info
    if _model is not None:
        return _model
    _prep_dll_path()
    if env.has_model():
        # 有本地模型就绝不联网：代理下 HF 的版本检查能卡几分钟
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    else:
        if on_note:
            on_note("首次使用需下载模型（约 1.6GB，只需一次）…")
        env.download_model()
    from faster_whisper import WhisperModel

    ref = str(env.model_dir())
    want = device if device != "auto" else ("cuda" if env.gpu_available() else "cpu")
    if want == "cuda":
        pairs = (("cuda", "float16"), ("cpu", "int8"))
    else:
        pairs = (("cpu", "int8"),)
    last: Exception | None = None
    for dev, ct in pairs:
        try:
            if dev == "cpu" and on_note:
                on_note("加载模型（CPU 模式，长音频会慢一些）…")
            _model = WhisperModel(ref, device=dev, compute_type=ct)
            _model_info = f"{MODEL_NAME} · {dev}/{ct}"
            return _model
        except Exception as e:  # 显存不足等情况回落 CPU
            last = e
    raise RuntimeError(f"模型加载失败：{last}\n模型目录：{ref}")


# ---------------- 转录 ----------------

def transcribe(path: Path, language: str | None = None, on_progress=None,
               on_segment=None, should_stop=None, beam_size: int = 5,
               on_note=None) -> Result:
    """转录一个媒体文件。on_progress(已处理秒, 总秒)，on_note(阶段文字)。"""
    if not env.find_ffmpeg_or_av():
        raise RuntimeError("无法解码音频：请安装 ffmpeg，或 pip install av；"
                           "也可用环境变量 W2T_FFMPEG 指定 ffmpeg 路径")
    repaired = False
    if repair.needs_repair(path):
        path = repair.repair(path, on_note=on_note)
        repaired = True
    total = media_duration(path)
    res = Result(source=path, duration=total, engine=_model_info, repaired=repaired)
    tmp_dir = Path(tempfile.mkdtemp(prefix="w2t_"))
    t0 = time.time()
    try:
        if on_note:
            on_note("解码音频…")
        wav = extract_wav(path, tmp_dir)
        if total <= 0:
            total = wav_duration(wav) or media_duration(wav)
            res.duration = total
        model = load_model(on_note=on_note)
        if on_note:
            on_note("开始转写…")
        seg_iter, info = model.transcribe(
            str(wav),
            language=language,
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,
        )
        res.language = info.language or "?"
        for s in seg_iter:
            text = (s.text or "").strip()
            res.segments.append(Segment(round(s.start, 2), round(s.end, 2), text))
            if on_segment:
                on_segment(res.segments[-1])
            if on_progress:
                on_progress(min(s.end, total or s.end), total)
            if should_stop and should_stop():
                break
    finally:
        # 清掉临时 wav
        for f in tmp_dir.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass
    if on_progress and res.segments:
        on_progress(res.duration or res.segments[-1].end, res.duration)
    res.engine = f"{_model_info} · 耗时 {fmt_hms(time.time() - t0)}"
    return res


def render_text(res: Result, ext: str) -> str:
    """纯文本类格式的渲染入口。"""
    return {"txt": lambda: res.plain + "\n", "md": res.markdown, "srt": lambda: res.srt() + "\n",
            "vtt": res.vtt, "json": res.json_text}[ext]()


def write_outputs(res: Result, out_dir: Path,
                  formats=("txt", "md", "srt", "docx")) -> list[Path]:
    """按格式落盘。docx 走自动排版；缺 python-docx 时静默跳过。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r'[<>:"/\\|?*]', "_", res.source.name.rsplit(".", 1)[0])[:80]
    paths = []
    for ext in formats:
        p = out_dir / f"{stem}.{ext}"
        if ext == "docx":
            try:
                import docx_export

                docx_export.save(res, p, mode="blocks")
            except ImportError:
                continue
        else:
            p.write_text(render_text(res, ext), encoding="utf-8")
        paths.append(p)
    return paths


# ---------------- CLI ----------------

def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    lang = next((a.split("=", 1)[1] for a in argv[1:] if a.startswith("--lang=")), None)
    out = next((a.split("=", 1)[1] for a in argv[1:] if a.startswith("--out=")), "output")
    fmts = tuple(next((a.split("=", 1)[1] for a in argv[1:] if a.startswith("--fmt=")),
                      "txt,md,srt,docx").split(","))
    if not args:
        print("用法: python transcribe.py <媒体文件> [--lang=zh] [--out=目录]")
        return 2
    path = Path(args[0])
    last = [0.0]

    def prog(done, total):
        if total and done - last[0] >= total / 40:
            last[0] = done
            print(f"  {done / total * 100:5.1f}%  [{fmt_ts(done)}]", flush=True)

    r = transcribe(path, lang, on_progress=prog,
                   on_segment=lambda s: print(f"[{fmt_ts(s.start)}] {s.text}", flush=True))
    files = write_outputs(r, Path(out), fmts)
    print(f"\n语言 {r.language} · 句数 {len(r.segments)} · {r.engine}")
    for f in files:
        print("  ->", f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
