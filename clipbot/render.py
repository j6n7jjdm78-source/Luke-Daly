"""Cut a clip to 9:16 with burned-in word-chunk captions using ffmpeg."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .transcribe import Segment, Word


def _ts(t: float) -> str:
    t = max(t, 0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def words_in(segments: list[Segment], start: float, end: float) -> list[Word]:
    return [w for s in segments for w in s.words if w.start >= start and w.end <= end]


def build_ass(words: list[Word], start: float, font: str, size: int, per_chunk: int = 3,
              credit: str = "", duration: float = 0, credit_pos: str = "top-left") -> str:
    head = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n"
        "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
        "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,"
        "Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,5,2,2,60,60,520,1\n"
        f"Style: Credit,{font},30,&H70FFFFFF,&H70FFFFFF,&H50000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,2,0,{7 if credit_pos == 'top-left' else 1},50,50,"
        f"{120 if credit_pos == 'top-left' else 90},1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    )
    lines = []
    if credit:
        c = credit.replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(duration)},Credit,,0,0,0,,{c}")
    for i in range(0, len(words), per_chunk):
        chunk = words[i:i + per_chunk]
        text = " ".join(w.text for w in chunk).upper().replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 0,{_ts(chunk[0].start - start)},{_ts(chunk[-1].end - start)},"
                     f"Default,,0,0,0,,{text}")
    return head + "\n".join(lines) + "\n"


def render_clip(video: Path, start: float, end: float, words: list[Word],
                out: Path, cfg: dict, credit: str = "") -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    ass_name = out.with_suffix(".ass").name
    credit = credit if cfg.get("credit", True) else ""
    use_caps = bool(credit) or (cfg.get("captions", True) and words)
    if use_caps:
        (out.parent / ass_name).write_text(
            build_ass(words if cfg.get("captions", True) else [], start, cfg["font"],
                      cfg["font_size"], credit=credit, duration=end - start,
                      credit_pos=cfg.get("credit_position", "top-left")), encoding="utf-8")
    sub = f",ass={ass_name}" if use_caps else ""
    if cfg.get("layout") == "crop":
        vf = f"scale=-2:1920,crop=1080:1920{sub}"
    else:
        vf = ("split[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,"
              "crop=1080:1920,boxblur=25:5[bg];[b]scale=1080:-2[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2{sub}")
    subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", str(video.resolve()),
         "-filter_complex" if cfg.get("layout") != "crop" else "-vf", vf,
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out.name],
        check=True, capture_output=True, cwd=out.parent,
    )
    return out
