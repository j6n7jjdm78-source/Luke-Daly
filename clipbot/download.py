"""Download a (finished) YouTube live stream / VOD with yt-dlp."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def download(url: str, workdir: Path, cfg: dict) -> tuple[Path, dict]:
    workdir.mkdir(parents=True, exist_ok=True)
    h = cfg.get("max_height", 1080)
    out = str(workdir / "%(id)s.%(ext)s")
    cmd = [
        "yt-dlp", "--no-playlist", "-f",
        f"bv*[height<={h}]+ba/b[height<={h}]",
        "--merge-output-format", "mp4",
        "--write-info-json", "-o", out, "--print", "after_move:filepath", url,
    ]
    if cfg.get("start") or cfg.get("end"):
        cmd += ["--download-sections", f"*{cfg.get('start', '0')}-{cfg.get('end', 'inf')}"]
    res = subprocess.run(cmd, check=True, capture_output=True, text=True)
    video = Path(res.stdout.strip().splitlines()[-1])
    info_path = video.with_suffix(".info.json")
    info = json.loads(info_path.read_text()) if info_path.exists() else {}
    return video, info
