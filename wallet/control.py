"""Owner-only Telegram control. Pure command handler; the loop that feeds it updates lives in trader.py.
Allowed: /status /address /stop /sellall /help. Never: switch to live, change limits, change allowlist, export key, move funds."""
import os

HELP = "Commands: /status /address /stop (halt new buys) /sellall (close everything) /help"


def handle(update, owner_id, state_dir, root, address=None, status_text=lambda: "ok"):
    """update: a Telegram `message` update. Returns reply text, or None to ignore silently (wrong sender/chat/unknown)."""
    m = update.get("message")
    if not m:
        return None
    if (m.get("from") or {}).get("id") != owner_id or (m.get("chat") or {}).get("type") != "private":
        return None
    cmd = (m.get("text") or "").strip().split()[0].split("@")[0].lower() if (m.get("text") or "").strip() else ""
    if cmd == "/stop":
        open(os.path.join(root, "STOP"), "w").close()
        return "STOP created: no new buys. Open positions keep their exit rules. To resume, delete STOP on the server."
    if cmd == "/sellall":
        open(os.path.join(root, "SELLALL"), "w").close()
        return "SELLALL created: closing all positions."
    if cmd == "/address":
        return f"Fund this PUBLIC address from your own wallet: {address}" if address else "No wallet created yet (run keygen on the server)."
    if cmd == "/status":
        return status_text()
    if cmd in ("/help", "/start"):
        return HELP
    return None
