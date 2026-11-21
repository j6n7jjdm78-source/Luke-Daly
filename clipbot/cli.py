"""clipbot: live / recently-ended YouTube stream -> Shorts.

  python -m clipbot URL [--no-upload] [--config config.yaml]
"""
from __future__ import annotations

import argparse
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from .download import download
from .render import render_clip, words_in
from .select import select_clips
from .source import StaleStream, check_fresh, probe, record_chunk
from .transcribe import transcribe

STATE = Path("state.json")
_lock = threading.Lock()


def _load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def process(video: Path, tag: str, url: str, cfg: dict, upload_on: bool) -> None:
    """Transcribe -> pick -> render -> (upload) for one video file."""
    work = video.parent
    segments = transcribe(video, work, cfg["transcribe"])
    clips = select_clips(segments, cfg["select"])
    print(f"[{tag}] {len(clips)} clip(s) selected")
    for c in clips:
        key = f"{tag}:{c.start:.0f}-{c.end:.0f}"
        with _lock:
            state = _load_state()
        if key in state:
            continue
        out = render_clip(video, c.start, c.end, words_in(segments, c.start, c.end),
                          Path("output") / f"{tag}_{c.start:.0f}.mp4", cfg["render"])
        print(f"[{tag}] rendered {out.name} [{c.score}] {c.title} ({c.end - c.start:.0f}s)")
        yt_id = None
        if upload_on:
            from .upload import upload
            desc = c.description
            if cfg["upload"].get("credit_source"):
                desc += f"\n\nSource: {url}"
            yt_id = upload(out, c.title, desc, cfg["upload"])
            print(f"[{tag}] uploaded https://youtube.com/shorts/{yt_id}")
        with _lock:
            state = _load_state()
            state[key] = {"file": str(out), "youtube_id": yt_id, "title": c.title}
            STATE.write_text(json.dumps(state, indent=2))


def run_live(url: str, vid: str, cfg: dict, upload_on: bool) -> None:
    secs = int(cfg["source"]["chunk_minutes"] * 60)
    maxh = cfg["download"].get("max_height", 1080)
    pool = ThreadPoolExecutor(max_workers=1)  # process chunk N while recording N+1
    n = 0
    while True:
        chunk = record_chunk(url, Path("work") / vid / f"c{n}" / "chunk.mkv", secs, maxh)
        if chunk.exists() and chunk.stat().st_size > 0:
            fut = pool.submit(process, chunk, f"{vid}-c{n}", url, cfg, upload_on)
            fut.add_done_callback(lambda f: f.exception() and print("chunk failed:", f.exception()))
        n += 1
        try:
            if check_fresh(probe(url), cfg["source"]["max_age_hours"]) != "live":
                break
        except StaleStream:
            break
        except Exception as e:  # transient probe failure: keep recording
            print("probe failed:", e)
    print("Stream ended; finishing processing...")
    pool.shutdown(wait=True)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="clipbot")
    ap.add_argument("url", help="YouTube stream URL (live now, or ended < 24h ago)")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--no-upload", action="store_true", help="render only")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(Path(a.config).read_text())
    upload_on = cfg["upload"]["enabled"] and not a.no_upload

    info = probe(a.url)
    try:
        mode = check_fresh(info, cfg["source"]["max_age_hours"])
    except StaleStream as e:
        raise SystemExit(f"Refusing: {e}")
    vid = info["id"]
    print(f"Stream is {'LIVE' if mode == 'live' else 'a recent VOD'}: {info.get('title')}")
    if mode == "live":
        run_live(a.url, vid, cfg, upload_on)
    else:
        video, _ = download(a.url, Path("work") / vid, cfg["download"])
        process(video, vid, a.url, cfg, upload_on)


if __name__ == "__main__":
    main()
