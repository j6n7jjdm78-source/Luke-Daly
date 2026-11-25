"""Export XAUUSD candles from your MT5 DEMO terminal to data/xauusd_{5m,15m,1h}.csv (UTC).
Windows:  py gold\\mt5_export.py [--bars 50000]
Then backtest on the real broker data:  py gold\\lab.py xauusd"""
import argparse, csv, json, os, sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from broker import MT5Broker

ap = argparse.ArgumentParser()
ap.add_argument("--bars", type=int, default=50000, help="candles per timeframe (broker may return fewer)")
a = ap.parse_args()
cfg = json.load(open(os.path.join(HERE, "config.json")))
b = MT5Broker(cfg)
out = os.path.join(HERE, "..", "data")
os.makedirs(out, exist_ok=True)
lines = []
for tf in ("5m", "15m", "1h"):
    rows = b.rates(tf, a.bars)
    path = os.path.join(out, f"xauusd_{tf}.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "time_utc", "open", "high", "low", "close", "volume", "spread_points"])
        for r in rows:
            w.writerow([r["ts"], datetime.fromtimestamp(r["ts"], timezone.utc).isoformat(), r["o"], r["h"], r["l"], r["c"], r["v"], r["sp"]])
    first = datetime.fromtimestamp(rows[0]["ts"], timezone.utc).date()
    last = datetime.fromtimestamp(rows[-1]["ts"], timezone.utc).date()
    print(f"{tf}: {len(rows)} candles {first} to {last} -> {path}")
    lines.append(f"| data/xauusd_{tf}.csv | MT5 demo terminal ({b.describe()}), symbol {cfg['symbol']} | {len(rows)} candles {first} to {last} | {datetime.now(timezone.utc).isoformat()} | times converted to UTC using offset {b.off // 3600}h |")
with open(os.path.join(out, "sources.md"), "a") as f:
    f.write("\n## MT5 exports\n| File | Source | What | Exported (UTC) | Notes |\n|---|---|---|---|---|\n" + "\n".join(lines) + "\n")
