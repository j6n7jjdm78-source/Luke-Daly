"""clipbot: live / recently-ended YouTube stream -> Shorts.

  python -m clipbot URL [--no-upload] [--config config.yaml]
  python -m clipbot --doctor      # preflight checks
  python -m clipbot --analyze     # pull retention stats into insights.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from . import growth
from .download import download
from .render import render_clip, words_in
from .select import select_clips
from .source import StaleStream, check_fresh, credit_handle, prepend_tail, probe, record_chunk
from .transcribe import transcribe

STATE = Path("state.json")
_lock = threading.Lock()


def load_env(path: str = ".env") -> None:
    p = Path(path)
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                if v.strip():
                    os.environ.setdefault(k.strip(), v.strip())


def _load_state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def overlaps(state: dict, stream: str, a: float, b: float) -> bool:
    """True if [a, b] (absolute stream seconds) overlaps a clip we already made."""
    return any(v.get("stream") == stream and a < v["abs_end"] and b > v["abs_start"]
               for v in state.values() if "abs_start" in v)


def process(video: Path, tag: str, url: str, cfg: dict, upload_on: bool, *, stream: str,
            credit: str = "", guide: str = "(none)", offset: float = 0.0,
            tail: float = 0.0) -> None:
    """Transcribe -> pick -> render -> (upload) one video file.

    offset: absolute stream second at which this file begins.
    tail:   seconds at the start already covered by the previous chunk.
    """
    segments = transcribe(video, video.parent, cfg["transcribe"])
    clips = [c for c in select_clips(segments, cfg["select"], guide) if c.end > tail + 1]
    print(f"[{tag}] {len(clips)} clip(s) selected")
    for c in clips:
        a, b = offset + c.start, offset + c.end
        with _lock:
            state = _load_state()
        if overlaps(state, stream, a, b):
            continue
        out = render_clip(video, c.start, c.end, words_in(segments, c.start, c.end),
                          Path("output") / f"{tag}_{c.start:.0f}.mp4", cfg["render"], credit)
        print(f"[{tag}] rendered {out.name} [{c.score}] {c.title} ({c.end - c.start:.0f}s)")
        yt_id, publish_at = None, None
        if upload_on:
            from .upload import first_comment, upload
            up = cfg["upload"]
            desc = c.description
            if up.get("credit_source"):
                src = f"{credit} - {url}" if credit else url
                desc += f"\n\nSource: {src}"
            if up.get("schedule"):
                with _lock:
                    taken = [v["publish_at"] for v in _load_state().values() if v.get("publish_at")]
                publish_at = growth.next_slot(taken, up["schedule"]["post_times"],
                                              up["schedule"]["timezone"])
            yt_id = upload(out, c.title, desc, up, publish_at)
            print(f"[{tag}] uploaded https://youtube.com/shorts/{yt_id}"
                  + (f" (publishes {publish_at})" if publish_at else ""))
            if up.get("first_comment"):
                first_comment(yt_id, up["first_comment"], up)
        with _lock:
            state = _load_state()
            state[f"{stream}:{a:.0f}-{b:.0f}"] = {
                "file": str(out), "youtube_id": yt_id, "title": c.title,
                "seconds": round(c.end - c.start), "publish_at": publish_at,
                "stream": stream, "abs_start": a, "abs_end": b}
            STATE.write_text(json.dumps(state, indent=2))


def run_live(url: str, vid: str, cfg: dict, upload_on: bool, credit: str, guide: str) -> None:
    secs = int(cfg["source"]["chunk_minutes"] * 60)
    ov = int(cfg["source"].get("overlap_seconds", 60))
    maxh = cfg["download"].get("max_height", 1080)
    pool = ThreadPoolExecutor(max_workers=1)  # process chunk N while recording N+1
    prev: Path | None = None
    n = 0
    while True:
        d = Path("work") / vid / f"c{n}"
        chunk = record_chunk(url, d / "chunk.mkv", secs, maxh)
        if chunk.exists() and chunk.stat().st_size > 0:
            media, tail, offset = chunk, 0.0, float(n * secs)
            if prev is not None and ov:
                try:
                    media, tail = prepend_tail(prev, chunk, ov, d / "joined.mkv")
                    offset = float(n * secs) - tail
                except Exception as e:  # fall back to the plain chunk
                    print("overlap failed:", e)
            fut = pool.submit(process, media, f"{vid}-c{n}", url, cfg, upload_on,
                              stream=vid, credit=credit, guide=guide, offset=offset, tail=tail)
            fut.add_done_callback(lambda f: f.exception() and print("chunk failed:", f.exception()))
            prev = chunk
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


def doctor(cfg: dict) -> int:
    ok = True

    def check(name: str, good: bool, hint: str = "") -> None:
        nonlocal ok
        ok &= good
        print(f"[{'ok' if good else 'MISSING'}] {name}" + (f"  -> {hint}" if not good else ""))

    check("ffmpeg", bool(shutil.which("ffmpeg")), "install ffmpeg")
    check("yt-dlp", bool(shutil.which("yt-dlp")), "pip install -r requirements.txt")
    check("ANTHROPIC_API_KEY", bool(os.environ.get("ANTHROPIC_API_KEY")), "put it in .env")
    try:
        import faster_whisper  # noqa: F401
        check("faster-whisper", True)
    except ImportError:
        check("faster-whisper", False, "pip install -r requirements.txt")
    up = cfg["upload"]
    check("client_secret.json", Path(up["client_secret"]).exists(), "Google Cloud OAuth Desktop client")
    check("YouTube login (token.json)", Path(up["token"]).exists(),
          "created on first upload (browser login)")
    check("rights_confirmed", bool(cfg.get("rights_confirmed")),
          "set true in config.yaml once you own / have permission for the streams")
    check("niche", bool(cfg.get("niche")), "set in config.yaml (optional, enables trend scouting)")
    return 0 if ok else 1


def main(argv=None) -> None:
    load_env()
    ap = argparse.ArgumentParser(prog="clipbot")
    ap.add_argument("url", nargs="?", help="YouTube stream URL (live now, or ended < 24h ago)")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--no-upload", action="store_true", help="render only")
    ap.add_argument("--doctor", action="store_true", help="preflight checks")
    ap.add_argument("--analyze", action="store_true", help="pull retention stats -> insights.json")
    a = ap.parse_args(argv)
    cfg = yaml.safe_load(Path(a.config).read_text())
    if a.doctor:
        raise SystemExit(doctor(cfg))
    upload_on = cfg["upload"]["enabled"] and not a.no_upload
    if a.analyze:
        from .upload import analytics_service
        print(json.dumps(growth.analyze(_load_state(), analytics_service(cfg["upload"])), indent=2))
        return
    if not a.url:
        ap.error("url required")
    if upload_on and not cfg.get("rights_confirmed"):
        raise SystemExit("Uploads blocked: set rights_confirmed: true in config.yaml once you "
                         "own or have permission to clip this stream (or use --no-upload).")

    info = probe(a.url)
    try:
        mode = check_fresh(info, cfg["source"]["max_age_hours"])
    except StaleStream as e:
        raise SystemExit(f"Refusing: {e}")
    vid, credit = info["id"], credit_handle(info)
    print(f"Stream is {'LIVE' if mode == 'live' else 'a recent VOD'}: {info.get('title')} ({credit})")

    trending = []
    if cfg.get("niche") and Path(cfg["upload"]["token"]).exists():
        try:
            from .upload import _service
            trending = growth.scout(cfg["niche"], _service(cfg["upload"]))
        except Exception as e:
            print("scout skipped:", e)
    guide = growth.guidance(trending)

    if mode == "live":
        run_live(a.url, vid, cfg, upload_on, credit, guide)
    else:
        video, _ = download(a.url, Path("work") / vid, cfg["download"])
        process(video, vid, a.url, cfg, upload_on, stream=vid, credit=credit, guide=guide)


if __name__ == "__main__":
    main()
