"""Compact scan report (same text the 20-minute DM sends): candidates, why they fail, what passes, near-misses. Posts nothing."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot
print(bot.scan_summary())
