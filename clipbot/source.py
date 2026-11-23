"""Stream metadata, 24h freshness check, and live recording."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path


class StaleStream(Exception):
    pass


def probe(url: str) -> dict:
    r = subprocess.run(["yt-dlp", "-J", "--no-download", "--no-playlist", url],
                       check=True, capture_output=True, text=True)
    return json.loads(r.stdout)


def hours_since_end(info: dict, now: float | None = None) -> float | None:
    """Hours since the stream ended; 0 if live; None if unknown."""
    now = now or time.time()
    if info.get("live_status") == "is_live" or info.get("is_live"):
        return 0.0
    start = info.get("release_timestamp") or info.get("timestamp")
    if start and info.get("duration"):
        return (now - (start + info["duration"])) / 3600
    if info.get("timestamp"):  # ended time unknown: upload time is a close upper bound
        return (now - info["timestamp"]) / 3600
    return None


def check_fresh(info: dict, max_age_hours: float) -> str:
    """Return 'live' or 'vod'; raise StaleStream if not live or recent enough."""
    status = info.get("live_status")
    if status == "is_upcoming":
        raise StaleStream("stream hasn't started yet")
    if status not in ("is_live", "was_live", "post_live"):
        raise StaleStream(f"not a live stream (live_status={status!r})")
    age = hours_since_end(info)
    if age is None:
        raise StaleStream("can't determine when the stream ended")
    if age > max_age_hours:
        raise StaleStream(f"stream ended {age:.1f}h ago (limit {max_age_hours}h)")
    return "live" if status == "is_live" else "vod"


def stream_urls(url: str, max_height: int) -> list[str]:
    r = subprocess.run(["yt-dlp", "-g", "--no-playlist", "-f",
                        f"bv*[height<={max_height}]+ba/b[height<={max_height}]", url],
                       check=True, capture_output=True, text=True)
    return r.stdout.split()


def record_chunk(url: str, out: Path, seconds: int, max_height: int) -> Path:
    """Record `seconds` from the live edge (ends early if the stream ends)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    urls = stream_urls(url, max_height)
    for u in urls:
        cmd += ["-i", u]
    cmd += ["-t", str(seconds), "-c", "copy", str(out)]
    subprocess.run(cmd, check=False, capture_output=True)
    return out


def credit_handle(info: dict) -> str:
    """Best '@handle' for the stream's creator, falling back to the channel name."""
    uid = info.get("uploader_id") or ""
    if uid.startswith("@"):
        return uid
    url = info.get("channel_url") or info.get("uploader_url") or ""
    if "/@" in url:
        return "@" + url.split("/@", 1)[1].split("/")[0]
    return info.get("channel") or info.get("uploader") or ""


def duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True)
    return float(r.stdout.strip())


def prepend_tail(prev: Path, new: Path, seconds: int, out: Path) -> tuple[Path, float]:
    """out = last ~`seconds` of prev + all of new (so moments spanning chunks survive).

    Stream copy cuts on a keyframe, so the real tail can be longer than asked; returns
    (out, actual_tail_seconds)."""
    tail = out.with_name("tail.mkv")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-sseof", f"-{seconds}", "-i",
                    str(prev), "-c", "copy", str(tail)], check=True, capture_output=True)
    lst = out.with_name("concat.txt")
    lst.write_text(f"file '{tail.resolve()}'\nfile '{new.resolve()}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i",
                    str(lst), "-c", "copy", str(out)], check=True, capture_output=True)
    return out, duration(tail)
