"""Runs the bot every 10 minutes until you close the window. Works on Mac, Windows, Linux.
Start with: python3 bot/run_loop.py   (Windows: python bot\\run_loop.py)"""
import subprocess, sys, time, os
here = os.path.dirname(os.path.abspath(__file__))
while True:
    subprocess.run([sys.executable, os.path.join(here, "bot.py")])
    time.sleep(600)
