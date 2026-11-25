"""Fetch gold proxy candles (PAXG/USD) from Kraken public API. No keys, paper research only.
Appends new candles to data/paxgusd_<tf>.csv (UTC, deduplicated). Run it regularly to build history.
"""
import csv, json, os, sys, time, urllib.request
from datetime import datetime, timezone

PAIR = "PAXGUSD"
TFS = {5: "5m", 15: "15m", 60: "1h"}
DATA = os.path.join(os.path.dirname(__file__), "..", "data")
UA = "gold-paper-lab/0.1 (research, low rate)"

def fetch(interval):
    url = f"https://api.kraken.com/0/public/OHLC?pair={PAIR}&interval={interval}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.load(r)
    if d.get("error"):
        raise RuntimeError(d["error"])
    key = [k for k in d["result"] if k != "last"][0]
    # last row is the still-forming candle: drop it (no lookahead)
    return d["result"][key][:-1]

def merge(path, rows):
    have = {}
    if os.path.exists(path):
        with open(path) as f:
            for r in csv.DictReader(f):
                have[int(r["ts"])] = r
    for t, o, h, l, c, vwap, v, n in rows:
        have[int(t)] = dict(ts=int(t), time_utc=datetime.fromtimestamp(int(t), timezone.utc).isoformat(),
                            open=o, high=h, low=l, close=c, volume=v, trades=n)
    cols = ["ts", "time_utc", "open", "high", "low", "close", "volume", "trades"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for k in sorted(have): w.writerow(have[k])
    return len(have)

if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    for iv, name in TFS.items():
        rows = fetch(iv)
        n = merge(os.path.join(DATA, f"paxgusd_{name}.csv"), rows)
        print(f"{name}: {n} candles stored, fetched {len(rows)} at {datetime.now(timezone.utc).isoformat()}")
        time.sleep(2)
