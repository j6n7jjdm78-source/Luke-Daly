"""Runs the bot every 5 minutes until stopped. Works on Mac, Windows, Linux.
Start with: python3 bot/run_loop.py   (Windows: python bot\\run_loop.py)
Writes state/heartbeat every cycle. Sends the owner private Telegram reports: start notice, scan report every 20 minutes, daily summary."""
import subprocess, sys, time, os, datetime as dt
here = os.path.dirname(os.path.abspath(__file__)); root = os.path.dirname(here)
os.makedirs(os.path.join(root, "state"), exist_ok=True)
sys.path.insert(0, here)
import bot

def run(script):
    r = subprocess.run([sys.executable, os.path.join(here, script)], capture_output=True, text=True, timeout=240)
    return (r.stdout or "").strip()

bot.owner_msg(f"🔄 Bot started {dt.datetime.now(dt.timezone.utc):%H:%M} UTC (first start, or restarted after the machine restarted).")
cycle = 0
while True:
    open(os.path.join(root, "state", "heartbeat"), "w").write(str(int(time.time())))
    subprocess.run([sys.executable, os.path.join(here, "bot.py")])
    cycle += 1
    try:
        if cycle % 4 == 0:                      # every 20 minutes
            bot.owner_msg("🔎 " + run("scan_report.py"))
        now = dt.datetime.now(dt.timezone.utc); mark = os.path.join(root, "state", f"daily-{now.date()}")
        if (now.hour, now.minute) >= (23, 45) and not os.path.exists(mark):   # once a day
            open(mark, "w").close(); bot.owner_msg("📊 Daily summary\n" + run("status.py"))
    except Exception:
        pass
    time.sleep(300)
