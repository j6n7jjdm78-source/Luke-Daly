import subprocess
from pathlib import Path

from clipbot.render import build_ass, render_clip
from clipbot.select import parse_clips, validate
from clipbot.transcribe import Segment, Word


def test_parse_and_validate():
    raw = parse_clips('Sure!\n[{"start": 10, "end": 50, "score": 8, "title": "t"},'
                      '{"start": 60, "end": 65, "score": 9, "title": "short"}]')
    segs = [Segment(0, 100, "x", [])]
    clips = validate(raw, segs, 20, 59)
    assert len(clips) == 1 and clips[0].title == "t"
    assert parse_clips("no json") == []


def test_render(tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=s=1280x720:d=4:r=25",
                    "-f", "lavfi", "-i", "sine=d=4", "-shortest", str(src)],
                   check=True, capture_output=True)
    words = [Word(0.5, 1, "hello"), Word(1, 1.5, "big"), Word(1.5, 2, "world")]
    assert "HELLO BIG WORLD" in build_ass(words, 0, "Arial", 72)
    for layout in ("blur", "crop"):
        out = render_clip(src, 0, 3, words, tmp_path / f"{layout}.mp4",
                          {"layout": layout, "captions": True, "font": "Arial", "font_size": 72})
        assert out.stat().st_size > 1000


def test_freshness():
    import time
    import pytest
    from clipbot.source import StaleStream, check_fresh
    now = time.time()
    live = {"live_status": "is_live"}
    assert check_fresh(live, 24) == "live"
    recent = {"live_status": "was_live", "release_timestamp": now - 5 * 3600, "duration": 3600}
    assert check_fresh(recent, 24) == "vod"
    old = {"live_status": "was_live", "release_timestamp": now - 40 * 3600, "duration": 3600}
    with pytest.raises(StaleStream):
        check_fresh(old, 24)
    with pytest.raises(StaleStream):
        check_fresh({"live_status": "not_live"}, 24)


def test_next_slot_and_guidance(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from clipbot import growth
    now = datetime(2026, 11, 23, 14, 0, tzinfo=timezone.utc)  # 09:00 New York
    times = ["09:00", "13:00", "18:00"]
    a = growth.next_slot([], times, "America/New_York", now)
    assert a == "2026-11-23T18:00:00Z"            # 13:00 NY
    b = growth.next_slot([a], times, "America/New_York", now)
    assert b == "2026-11-23T23:00:00Z"            # 18:00 NY
    monkeypatch.setattr(growth, "INSIGHTS", tmp_path / "none.json")
    assert "no performance data" in growth.guidance()
    assert "Titles currently" in growth.guidance([{"title": "x", "views": 1}])
