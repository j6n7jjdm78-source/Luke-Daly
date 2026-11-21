"""Liest X_CLIENT_ID und X_CLIENT_SECRET: zuerst aus Umgebungsvariablen, sonst aus
~/.config/cliperz-bot/keys.env (liegt außerhalb des Bot-Ordners, wird nie mitverschickt).
Werte werden nie ausgegeben."""
import os

DIR = os.path.join(os.path.expanduser("~"), ".config", "cliperz-bot")
KEYS = os.path.join(DIR, "keys.env")
TOK = os.path.join(DIR, "tokens.json")


def load():
    vals = {}
    if os.path.exists(KEYS):
        for line in open(KEYS, encoding="utf-8"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    out = []
    for name in ("X_CLIENT_ID", "X_CLIENT_SECRET"):
        v = os.environ.get(name) or vals.get(name)
        if not v:
            raise SystemExit(f"{name} fehlt: als Umgebungsvariable setzen oder in {KEYS} eintragen (siehe SETUP.md).")
        out.append(v)
    return tuple(out)
