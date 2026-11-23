"""Watchdog: runs on its own GitHub schedule (so it still works when the bot job itself is dead) and sends the owner ONE private Telegram DM
when the bot looks stalled. It only reads the Actions run list and the commit list. Needs GITHUB_TOKEN, GITHUB_REPOSITORY, TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_CHAT_ID."""
import datetime as dt, json, os, sys, urllib.parse, urllib.request

def _t(s): return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))

def assess(runs, commits, now):
    """Return a list of plain-language problems (empty = healthy). runs: newest-first workflow runs of bot.yml; commits: newest-first commits on main."""
    problems = []
    if not runs: return ["no bot runs found at all"]
    running = [x for x in runs if x["status"] == "in_progress"]
    waiting = [x for x in runs if x["status"] in ("queued", "pending", "waiting")]
    stuck = [x for x in running if (now - _t(x["run_started_at"])).total_seconds() > 65 * 60]      # jobs are capped at 50 minutes
    if stuck: problems.append(f"run #{stuck[0]['run_number']} has been 'in progress' for over 65 minutes (stuck)")
    if not running:
        last = max(_t(x["updated_at"]) for x in runs); idle = (now - last).total_seconds() / 60
        if idle > 25 and not waiting: problems.append(f"no bot run is active and the last one ended {idle:.0f} minutes ago")
        elif idle > 45: problems.append(f"the next bot run has been waiting {idle:.0f} minutes to start")
    done = [x for x in runs if x["status"] == "completed"][:3]
    bad = [x for x in done if x.get("conclusion") not in ("success", "cancelled")]
    if len(done) >= 2 and len(bad) >= 2: problems.append(f"{len(bad)} of the last {len(done)} bot runs failed (latest: run #{bad[0]['run_number']})")
    saves = [c for c in commits if (c.get("commit", {}).get("author", {}).get("name") == "cliperz-bot")]
    if saves:
        age_h = (now - _t(saves[0]["commit"]["author"]["date"])).total_seconds() / 3600
        if age_h > 3: problems.append(f"no bot state has been saved for {age_h:.1f} hours")
    else: problems.append("no bot state commits found on main")
    return problems

def should_alert(now):
    """At most one DM per 2 hours while a problem lasts (the schedule runs every 30 minutes)."""
    return now.hour % 2 == 0 and now.minute < 30

def _api(path):
    req = urllib.request.Request("https://api.github.com" + path, headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"], "Accept": "application/vnd.github+json"})
    return json.load(urllib.request.urlopen(req, timeout=30))

def main():
    repo = os.environ["GITHUB_REPOSITORY"]; now = dt.datetime.now(dt.timezone.utc)
    runs = _api(f"/repos/{repo}/actions/workflows/bot.yml/runs?per_page=8")["workflow_runs"]
    commits = _api(f"/repos/{repo}/commits?sha=main&per_page=40")
    problems = assess(runs, commits, now)
    print("watchdog:", problems or "healthy")
    if not problems or not (should_alert(now) or os.environ.get("FORCE_ALERT")): return
    msg = "🐕 Watchdog: the Cliperz bot looks stalled.\n- " + "\n- ".join(problems) + f"\nhttps://github.com/{repo}/actions"
    data = urllib.parse.urlencode({"chat_id": os.environ["TELEGRAM_OWNER_CHAT_ID"], "text": msg}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage", data, timeout=30)

if __name__ == "__main__": main()
