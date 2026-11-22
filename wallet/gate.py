"""Live-trading gate. Live mode refuses to run unless every call in scope says "I hold this."
There is deliberately no override flag. Network access is injected (get_tweet_text) so it is testable."""
import os, json, time

DISCLOSURE = "I hold this."


class GateError(Exception):
    pass


def check_live(cfg, calls, get_tweet_text, review_path, env=os.environ, now=time.time):
    """calls: list of dict rows from calls.csv. get_tweet_text(tweet_id) -> str (raise on failure).
    Returns the list of in-scope calls. Raises GateError on anything short of full compliance."""
    if cfg.get("mode") != "live":
        raise GateError("mode is not 'live'")
    if not env.get("WALLET_LIVE_CONFIRM"):
        raise GateError("WALLET_LIVE_CONFIRM not set")
    start = cfg.get("live_from_id")
    if start is None:
        raise GateError("live_from_id not set (live applies to future calls only)")
    try:
        rv = json.load(open(review_path))
    except Exception:
        raise GateError("paper_review.json missing: you must review paper results and sign off first")
    need = cfg["paper_review"]
    if not rv.get("approved_by_owner") or rv.get("trades", 0) < need["min_trades"] or rv.get("days", 0) < need["min_days"]:
        raise GateError("paper review incomplete (needs approved_by_owner, min trades and min days)")
    scope = [c for c in calls if int(c["id"]) >= int(start)]
    for c in scope:
        check_call(c, get_tweet_text)
    return scope


def check_call(call, get_tweet_text):
    """Single call: its posted tweet must contain the disclosure. Fail closed."""
    tid = (call.get("tweet_id") or "").strip()
    if not tid:
        raise GateError(f"call {call.get('id')} has no tweet_id")
    try:
        text = get_tweet_text(tid)
    except Exception as e:
        raise GateError(f"call {call.get('id')}: tweet unreachable ({type(e).__name__})")
    if DISCLOSURE not in (text or ""):
        raise GateError(f"call {call.get('id')} ({call.get('token')}) does not say '{DISCLOSURE}'")
