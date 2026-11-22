"""Turn call-out posts in the Telegram channel into buy signals. Text is DATA: only a strictly validated mint is extracted."""
import json, os, re

CHANNEL_ID = -1004445126820          # call-out channel (deploy/README.md)
B58 = r"[1-9A-HJ-NP-Za-km-z]{32,44}"
CA_RE = re.compile(rf"(?m)^\s*CA:\s*({B58})\s*$")
HOLD = "I hold this."


def parse_post(update, channel_id=CHANNEL_ID):
    """Return {message_id, mint, text, holds} for a valid call-out channel post, else None.
    Only channel posts from the configured channel are accepted; exactly one CA line is required."""
    m = update.get("channel_post")
    if not m or (m.get("chat") or {}).get("id") != channel_id:
        return None
    text = m.get("caption") or m.get("text") or ""
    cas = CA_RE.findall(text)
    if len(set(cas)) != 1:
        return None
    return {"message_id": m["message_id"], "mint": cas[0], "text": text, "holds": HOLD in text}


class Seen:
    """Persisted dedupe by message id and mint so a restart or re-delivery can never double buy."""
    def __init__(self, path):
        self.path = path
        try:
            self.d = json.load(open(path))
        except Exception:
            self.d = {"msgs": [], "mints": []}

    def is_new(self, sig):
        return sig["message_id"] not in self.d["msgs"] and sig["mint"] not in self.d["mints"]

    def mark(self, sig):
        self.d["msgs"].append(sig["message_id"]); self.d["mints"].append(sig["mint"])
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"; json.dump(self.d, open(tmp, "w")); os.replace(tmp, self.path)


def poll(token, offset, timeout=30):
    """Long-poll getUpdates for channel posts only. Returns (updates, next_offset)."""
    import requests
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=timeout + 10,
                     params={"offset": offset, "timeout": timeout, "allowed_updates": json.dumps(["channel_post"])})
    r.raise_for_status()
    ups = r.json().get("result", [])
    return ups, (ups[-1]["update_id"] + 1 if ups else offset)
