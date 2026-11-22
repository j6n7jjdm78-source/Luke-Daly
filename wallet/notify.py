"""Private owner notifications. Never raises: a Telegram problem must not affect trading."""
import requests


def send(token, chat_id, text):
    if not token or not chat_id:
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=10,
                          json={"chat_id": chat_id, "text": text[:3900], "disable_web_page_preview": True})
        return r.ok
    except Exception:
        return False


def mismatch_alert(token, chat_id, mint, reason):
    """The post says 'I hold this.' but we did not buy."""
    return send(token, chat_id, f"URGENT: a call-out says 'I hold this.' but the wallet did NOT buy {mint}: {reason}. Edit or delete that post.")
