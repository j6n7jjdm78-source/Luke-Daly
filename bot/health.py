"""Health check for the running bot. Prints 'ALL OK' or a list of things worth telling the owner. Restarts the bot if it is down.
Usage: python3 bot/health.py"""
import os, sys, csv, json, time, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ST = f"{ROOT}/state"; os.makedirs(ST, exist_ok=True)
notes = []
# 1) is the loop alive and cycling?
alive = subprocess.run(["pgrep", "-f", "bot/run_loop.py"], capture_output=True).stdout.strip() != b""
hb = int(open(f"{ST}/heartbeat").read() or 0) if os.path.exists(f"{ST}/heartbeat") else 0
age = time.time() - hb
if os.path.exists(f"{ROOT}/STOP"):
    notes.append("STOP file present: posting is paused on purpose")
elif not alive or age > 720:
    subprocess.Popen(f"cd {ROOT} && nohup python3 bot/run_loop.py >> state/bot.log 2>&1 &", shell=True)
    notes.append(f"RESTARTED the bot ({'process was gone' if not alive else f'no heartbeat for {age/60:.0f} min'})")
# 2) what changed in the call log since the last check
rows = {r["id"]: r for r in csv.DictReader(open(f"{ROOT}/calls.csv"))}
last = json.load(open(f"{ST}/health_last.json")) if os.path.exists(f"{ST}/health_last.json") else {"rows": {}, "log": 0}
for i, r in rows.items():
    old = last["rows"].get(i)
    if old is None: notes.append(f"NEW CALL #{i} ${r['token']} at ${float(r['mcap_at_call'])/1000:.0f}k (tweet {r['tweet_id']})")
    elif old != r["status"]: notes.append(f"${r['token']} status {old} -> {r['status']}")
# 3) errors or skipped posts in the bot log since the last check
log = f"{ST}/bot.log"; size = os.path.getsize(log) if os.path.exists(log) else 0
start = last.get("log", 0) if size >= last.get("log", 0) else 0
if os.path.exists(log):
    with open(log, errors="ignore") as f:
        f.seek(start); new = f.read()
    for l in new.splitlines():
        if any(k in l for k in ("Traceback", "Error", "[WARN]", "could not make/upload", "[TG] could not")): notes.append("LOG: " + l.strip()[:140])
# 4) is the X login still good? (checked at most once an hour)
chk = f"{ST}/x_check"
if not os.path.exists(chk) or time.time() - os.path.getmtime(chk) > 3600:
    try:
        sys.path.insert(0, f"{ROOT}/bot"); import bot
        bot.http("https://api.x.com/2/users/me", headers={"Authorization": "Bearer " + bot.token()}); open(chk, "w").write("ok")
    except Exception as e: notes.append(f"X LOGIN PROBLEM: {getattr(e, 'code', type(e).__name__)}")
json.dump({"rows": {i: r["status"] for i, r in rows.items()}, "log": size}, open(f"{ST}/health_last.json", "w"))
print("ALL OK" if not notes else "\n".join(notes))
