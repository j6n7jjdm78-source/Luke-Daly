"""Growth loop: posting schedule, trend scouting, and analytics feedback.

Maps the 'Scout / Uploader / Analyst' ideas onto clipbot:
  next_slot   - spread uploads across the day (e.g. 4/day) via YouTube scheduled publishing
  scout       - top short-form titles in your niche (last 24h) as *style* references
  analyze     - read your retention stats, learn what hooks/lengths work
  guidance    - text injected into the clip-selection prompt from the two above
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

INSIGHTS = Path("insights.json")


def next_slot(taken: list[str], times: list[str], tz: str, now: datetime | None = None) -> str:
    """Next free posting slot (RFC3339 UTC) after `now`, skipping already-taken ones."""
    zone = ZoneInfo(tz)
    now = (now or datetime.now(timezone.utc)).astimezone(zone)
    taken_set = {datetime.fromisoformat(t.replace("Z", "+00:00")) for t in taken}
    for d in range(60):
        day = (now + timedelta(days=d)).date()
        for t in sorted(times):
            h, m = map(int, t.split(":"))
            slot = datetime(day.year, day.month, day.day, h, m, tzinfo=zone)
            if slot > now + timedelta(minutes=20) and slot.astimezone(timezone.utc) not in taken_set:
                return slot.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raise RuntimeError("no free slot in next 60 days")


def scout(niche: str, creds_service, limit: int = 10) -> list[dict]:
    """Top Shorts-length videos for `niche` published in the last 24h (title + views)."""
    after = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = creds_service.search().list(part="id", q=niche, type="video", order="viewCount",
                                    videoDuration="short", publishedAfter=after,
                                    maxResults=limit).execute()
    ids = [i["id"]["videoId"] for i in r.get("items", [])]
    if not ids:
        return []
    v = creds_service.videos().list(part="snippet,statistics", id=",".join(ids)).execute()
    return [{"title": i["snippet"]["title"], "views": int(i["statistics"].get("viewCount", 0))}
            for i in v.get("items", [])]


def analyze(state: dict, analytics_service, days: int = 30) -> dict:
    """Join per-video retention with our own clip metadata and save insights.json."""
    end = datetime.now(timezone.utc).date()
    r = analytics_service.reports().query(
        ids="channel==MINE", startDate=str(end - timedelta(days=days)), endDate=str(end),
        metrics="views,averageViewPercentage,averageViewDuration", dimensions="video",
        sort="-views", maxResults=50).execute()
    by_id = {v["youtube_id"]: v for v in state.values() if v.get("youtube_id")}
    rows = []
    for vid, views, pct, dur in r.get("rows", []):
        if vid in by_id:
            rows.append({"title": by_id[vid]["title"], "views": views, "avg_view_pct": pct,
                         "avg_view_sec": dur, "clip_sec": by_id[vid].get("seconds")})
    rows.sort(key=lambda x: x["avg_view_pct"], reverse=True)
    out = {"updated": datetime.now(timezone.utc).isoformat(), "best": rows[:5],
           "worst": rows[-5:] if len(rows) > 5 else []}
    INSIGHTS.write_text(json.dumps(out, indent=2))
    return out


def guidance(trending: list[dict] | None = None) -> str:
    """Prompt text built from past performance (+ optional trending titles)."""
    parts = []
    if INSIGHTS.exists():
        d = json.loads(INSIGHTS.read_text())
        if d.get("best"):
            parts.append("Our best-retaining past Shorts (copy the *style*, length and hook "
                         "type, not the content):\n" + "\n".join(
                             f"- \"{r['title']}\" ({r['avg_view_pct']:.0f}% avg viewed, "
                             f"{r.get('clip_sec') or '?'}s)" for r in d["best"]))
        if d.get("worst"):
            parts.append("Our worst performers (avoid this style):\n" + "\n".join(
                f"- \"{r['title']}\" ({r['avg_view_pct']:.0f}%)" for r in d["worst"]))
    if trending:
        parts.append("Titles currently winning in our niche (for title style only):\n" +
                     "\n".join(f"- {t['title']}" for t in trending[:8]))
    return "\n\n".join(parts) or "(no performance data yet)"
