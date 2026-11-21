"""clipbot: YouTube live stream -> Shorts.

  python -m clipbot URL [--no-upload] [--config config.yaml]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from .download import download
from .render import render_clip, words_in
from .select import select_clips
from .transcribe import transcribe

STATE = Path("state.json")


def _load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="clipbot")
    ap.add_argument("url", help="YouTube stream/VOD URL (stream must have ended)")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--no-upload", action="store_true", help="render only")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(Path(a.config).read_text())

    work = Path("work")
    print("Downloading...")
    video, info = download(a.url, work, cfg["download"])
    vid = info.get("id", video.stem)
    print("Transcribing...")
    segments = transcribe(video, work, cfg["transcribe"])
    print("Selecting clips...")
    clips = select_clips(segments, cfg["select"])
    print(f"{len(clips)} clip(s) selected")

    state = _load_state()
    for c in clips:
        key = f"{vid}:{c.start:.0f}-{c.end:.0f}"
        if key in state:
            print(f"skip (already done): {c.title}")
            continue
        out = render_clip(video, c.start, c.end, words_in(segments, c.start, c.end),
                          Path("output") / f"{vid}_{c.start:.0f}.mp4", cfg["render"])
        print(f"rendered {out} [{c.score}] {c.title}")
        yt_id = None
        if cfg["upload"]["enabled"] and not a.no_upload:
            from .upload import upload
            desc = c.description
            if cfg["upload"].get("credit_source"):
                desc += f"\n\nSource: {a.url}"
            yt_id = upload(out, c.title, desc, cfg["upload"])
            print(f"uploaded https://youtube.com/shorts/{yt_id}")
        state[key] = {"file": str(out), "youtube_id": yt_id, "title": c.title}
        STATE.write_text(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
