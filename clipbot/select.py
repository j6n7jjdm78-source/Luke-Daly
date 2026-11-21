"""Ask Claude to pick the most engaging short-form moments from a transcript."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .transcribe import Segment

PROMPT = """You are a ruthless short-form editor cutting YouTube Shorts from a YouTube \
live stream. Below is a timestamped transcript window ([seconds] text).

Pick up to {n} moments, each {lo}-{hi} seconds (ideal: 20-30). Rules:
- HOOK: the clip must grab attention in its first 2 seconds (a bold claim, question, \
punchline setup, shout, reaction). Start exactly on that line - cut greetings, filler, \
throat-clearing and dead air.
- PAYOFF: end right after the payoff (the joke lands, the reveal, the reaction). Never \
trail off or run past it. Shorter is better if the payoff arrives sooner.
- SELF-CONTAINED: a stranger must understand it with zero context.
- SKIP: intros/outros, "like and subscribe", sponsor reads, chat-reading lulls, rambling.
- Start/end on sentence boundaries using the timestamps shown. No overlaps.
- Score honestly 1-10; most moments are not a 7+.

Return ONLY a JSON array, no prose:
[{{"start": <sec>, "end": <sec>, "score": <1-10>, "title": "<=60 chars, curiosity-driven, \
no hashtags, no clickbait lies", "description": "1-2 sentences"}}]
Return [] if nothing is good enough.

Transcript:
{transcript}
"""


@dataclass
class Clip:
    start: float
    end: float
    score: float
    title: str
    description: str


def _windows(segments: list[Segment], minutes: float):
    size = minutes * 60
    cur, t0 = [], None
    for s in segments:
        if t0 is None:
            t0 = s.start
        if s.start - t0 > size and cur:
            yield cur
            cur, t0 = [], s.start
        cur.append(s)
    if cur:
        yield cur


def parse_clips(text: str) -> list[dict]:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict)]


def validate(raw: list[dict], segments: list[Segment], lo: float, hi: float) -> list[Clip]:
    end_of_video = segments[-1].end if segments else 0
    clips = []
    for d in raw:
        try:
            s, e = float(d["start"]), float(d["end"])
            clip = Clip(s, e, float(d.get("score", 0)), str(d["title"])[:100],
                        str(d.get("description", "")))
        except (KeyError, TypeError, ValueError):
            continue
        if e > end_of_video + 1:
            continue
        if e - s > hi:
            clip.end = s + hi
        if clip.end - clip.start < lo:
            continue
        clips.append(clip)
    return clips


def select_clips(segments: list[Segment], cfg: dict) -> list[Clip]:
    import anthropic

    client = anthropic.Anthropic()
    lo, hi = cfg["min_seconds"], cfg["max_seconds"]
    found: list[Clip] = []
    for win in _windows(segments, cfg["window_minutes"]):
        transcript = "\n".join(f"[{s.start:.1f}] {s.text}" for s in win)
        msg = client.messages.create(
            model=cfg["model"], max_tokens=2000,
            messages=[{"role": "user", "content": PROMPT.format(
                n=3, lo=lo, hi=hi, transcript=transcript)}],
        )
        found += validate(parse_clips(msg.content[0].text), win, lo, hi)

    found = [c for c in found if c.score >= cfg["min_score"]]
    found.sort(key=lambda c: c.score, reverse=True)
    chosen: list[Clip] = []
    for c in found:  # drop overlaps, keep best
        if all(c.end <= k.start or c.start >= k.end for k in chosen):
            chosen.append(c)
        if len(chosen) >= cfg["max_clips"]:
            break
    return sorted(chosen, key=lambda c: c.start)
