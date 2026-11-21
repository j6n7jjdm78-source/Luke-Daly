"""Word-level transcription with faster-whisper."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word]


def extract_audio(video: Path, wav: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
        check=True, capture_output=True,
    )
    return wav


def transcribe(video: Path, workdir: Path, cfg: dict) -> list[Segment]:
    from faster_whisper import WhisperModel

    wav = extract_audio(video, workdir / "audio.wav")
    device = cfg.get("device", "auto")
    model = WhisperModel(cfg.get("model", "small"), device=device,
                         compute_type="float16" if device == "cuda" else "int8")
    segs, _ = model.transcribe(str(wav), word_timestamps=True,
                               language=cfg.get("language"), vad_filter=True)
    out = []
    for s in segs:
        words = [Word(w.start, w.end, w.word.strip()) for w in (s.words or [])]
        out.append(Segment(s.start, s.end, s.text.strip(), words))
    return out
