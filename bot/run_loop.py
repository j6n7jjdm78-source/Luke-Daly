"""Runs the bot every 5 minutes until stopped. Works on Mac, Windows, Linux.
Start with: python3 bot/run_loop.py   (Windows: python bot\\run_loop.py)
Writes state/heartbeat every cycle so a health check can see that it is alive."""
import subprocess, sys, time, os
here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
os.makedirs(os.path.join(root, "state"), exist_ok=True)
while True:
    open(os.path.join(root, "state", "heartbeat"), "w").write(str(int(time.time())))
    subprocess.run([sys.executable, os.path.join(here, "bot.py")])
    time.sleep(300)
