"""Read-only access to calls.csv (existing schema; never written here)."""
import csv, os
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_calls(path=None):
    path = path or os.path.join(ROOT, "calls.csv")
    return list(csv.DictReader(open(path, newline="")))


def call_ts(row) -> float:
    return datetime.fromisoformat(row["called_at_utc"]).timestamp()
