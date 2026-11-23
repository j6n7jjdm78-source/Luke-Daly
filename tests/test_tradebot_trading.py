import json, pytest
from tradebot.app import App, LAMPORTS
from tradebot.app_db import AppDB
from tradebot.trade import Trade, TradeError, parse_mint, clean
from tradebot.keystore import b58encode
from wallet.safety import Unsafe

T = [1_000_000.0]; UID = 42
MINT = b58encode(bytes([5]) * 32); WSOL = "So11111111111111111111111111111111111111112"
CFG = {"brand": "TradeBot", "network": "mainnet", "mainnet_enabled": True, "admin_id": 999, "fee_bps": 100, "slippage_bps": 500,
       "min_liquidity_usd": 10_000, "buy_presets_sol": [0.1, 0.5, 1], "max_total_deposits_sol": 5,
       "execution": {"max_price_impact_pct": 8, "max_roundtrip_loss_pct": 15}}


class Market:
    def __init__(self): self.bal = 0; self.info = {"name": "Test <b>Coin</b>", "symbol": "TST", "price_usd": 0.00001, "mcap": 50000, "liq_usd": 40000, "age_h": 5}
    mint_ok = {"mint_authority": None, "freeze_authority": None}
    sell_ratio = 1.0; route = True; impact = "0.01"
    def token_info(self, m): return self.info
    def mint_info(self, m): return self.mint_ok
    def quote(self, i, o, amt, slip):
        if not self.route and o == WSOL: raise RuntimeError("no route")
        if i == WSOL: return {"outAmount": str(amt * 1000), "otherAmountThreshold": str(amt * 950), "priceImpactPct": self.impact}
        return {"outAmount": str(int(amt / 1000 * self.sell_ratio)), "otherAmountThreshold": str(int(amt / 1000 * 0.95)), "priceImpactPct": self.impact}
    def swap_instructions(self, q, user): return {"swapInstruction": {"fake": True}, "user": user}
    def token_balance(self, user, mint): return self.bal


class Sg:
    def __init__(self): self.calls, self.need_pin, self.fail = [], False, None
    def __call__(self, req):
        self.calls.append(req)
        if req["op"] == "create_wallet": return {"ok": True, "pubkey": "WALLET" + "1" * 38, "created": False}
        if req["op"] == "status": return {"ok": True, "pubkey": "W", "has_pin": True, "frozen": False, "paused": False, "addresses": []}
        if req["op"] == "swap":
            if self.fail: return {"ok": False, "error": self.fail}
            if req["side"] == "buy" and self.need_pin and req.get("pin") != "483920": return {"ok": False, "error": "PIN required for this trade size"}
            return {"ok": True, "sig": "SIGX", "confirmed": True, "fee_lamports": req["amount"] // 100 if req["side"] == "buy" else 2000000,
                    "est_tokens": req["min_out"], "est_sol": 300_000_000}
        return {"ok": False, "error": "x"}


@pytest.fixture
def env():
    T[0] = 1_000_000.0; mk, sg, db = Market(), Sg(), AppDB(":memory:")
    trade = Trade(sg, db, mk, CFG, lambda: T[0]); app = App(sg, db, dict(CFG), lambda pk: 3 * LAMPORTS, clock=lambda: T[0], trade=trade)
    app.mk, app.sg, app.log = mk, sg, []
    return app


def msg(t, mid=1): return {"message": {"message_id": mid, "from": {"id": UID}, "chat": {"id": UID, "type": "private"}, "text": t}}
def cb(d): return {"callback_query": {"id": "c", "from": {"id": UID}, "data": d, "message": {"message_id": 5, "chat": {"id": UID, "type": "private"}}}}
def run(app, u): a = app.handle(u); app.log += a; return a
def texts(a): return " ".join(x.get("text") or "" for x in a if x["op"] == "send")
def start(app): run(app, msg("/start"))


def test_parse_mint_and_clean():
    assert parse_mint(MINT) == MINT and parse_mint(f"  {MINT}\n") == MINT
    for bad in ("", "hello", MINT + "x", "0" * 44, WSOL, "a" * 31, None, "x" * 100, MINT[:-1] + "!"): assert parse_mint(bad) is None
    assert "<" not in clean("<script>alert(1)</script>") and len(clean("x" * 500)) <= 32 and clean(None) == "?"


def test_paste_shows_escaped_card_with_buttons(env):
    start(env); a = run(env, msg(MINT)); t = texts(a)
    assert "Test" in t and "<b>Coin</b>" not in t and "Liquidity" in t and "1% per trade" in t
    labels = [b["text"] for row in a[0]["keyboard"] for b in row]; assert "Buy 0.5 SOL" in labels and "Sell 50%" in labels


def test_random_text_ignored_and_trading_off_message(env):
    start(env); assert run(env, msg("hello there")) == []
    env.cfg["network"] = "devnet"; assert "not enabled" in texts(run(env, msg(MINT)))
    env.cfg["network"] = "mainnet"; env.cfg["mainnet_enabled"] = False; assert "not enabled" in texts(run(env, msg(MINT)))


def test_buy_flow_confirm_then_execute(env):
    start(env); run(env, msg(MINT)); a = run(env, cb("buy:1")); t = texts(a)
    assert "Confirm buy" in t and "0.5 SOL" in t and "0.00500 SOL" in t and "round-trip" in t
    r = run(env, cb("go")); assert "Bought $TST" in texts(r) and "SIGX" in texts(r)
    sw = [c for c in env.sg.calls if c["op"] == "swap"][0]
    assert sw["side"] == "buy" and sw["amount"] == LAMPORTS // 2 and sw["slippage_bps"] == 500 and sw["min_out"] > 0 and "pin" not in sw
    assert env.db.positions(UID)[0]["cost_lamports"] == LAMPORTS // 2
    tr = env.db.c.execute("SELECT side, fee, estimated FROM trades").fetchone(); assert tuple(tr) == ("buy", LAMPORTS // 200, 1)
    assert run(env, cb("go")) == [] or "Bought" not in texts(run(env, cb("go")))                      # confirm cannot be replayed


def test_confirm_expires_after_60s(env):
    start(env); run(env, msg(MINT)); run(env, cb("buy:0")); T[0] += 61
    assert [c for c in env.sg.calls if c["op"] == "swap"] == [] and "Bought" not in texts(run(env, cb("go")))


def test_big_buy_asks_for_pin_deletes_it_and_retries(env):
    env.sg.need_pin = True; start(env); run(env, msg(MINT)); run(env, cb("buy:2")); a = run(env, cb("go"))
    assert "PIN" in texts(a); b = run(env, msg("483920", mid=88))
    assert {"op": "delete", "chat_id": UID, "message_id": 88} in b and "Bought" in texts(b)
    assert all("483920" not in json.dumps(x) for x in env.log)
    assert [c for c in env.sg.calls if c["op"] == "swap"][-1]["pin"] == "483920"


def test_custom_amount_parsing(env):
    start(env); run(env, msg(MINT)); run(env, cb("buy:c"))
    for bad in ("abc", "-1", "0", "nan", "1e400", "5000", "0.0000000001", "x" * 50): assert "amount in SOL" in texts(run(env, msg(bad))), bad
    assert "Confirm buy" in texts(run(env, msg("0.25")))


def test_unsafe_tokens_refused_before_signer(env):
    start(env)
    env.mk.route = False; run(env, msg(MINT)); a = run(env, cb("buy:0")); assert "❌" in texts(a)
    env.mk.route = True; env.mk.mint_ok = {"mint_authority": "x", "freeze_authority": None}; run(env, msg(MINT)); assert "authority" in texts(run(env, cb("buy:0")))
    env.mk.mint_ok = Market.mint_ok; env.mk.sell_ratio = 0.5; run(env, msg(MINT)); assert "round-trip" in texts(run(env, cb("buy:0")))
    env.mk.sell_ratio = 1.0; env.mk.impact = "0.5"; run(env, msg(MINT)); assert "impact" in texts(run(env, cb("buy:0")))
    env.mk.impact = "0.01"; env.mk.info["liq_usd"] = 500; assert "Liquidity too low" in texts(run(env, msg(MINT)))
    assert [c for c in env.sg.calls if c["op"] == "swap"] == []


def test_signer_refusal_shown_and_not_recorded(env):
    start(env); run(env, msg(MINT)); run(env, cb("buy:0")); env.sg.fail = "daily trade limit reached"
    t = texts(run(env, cb("go"))); assert "daily trade limit" in t and env.db.positions(UID) == [] and env.db.c.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0


def test_sell_flow_reduces_cost_basis(env):
    start(env); run(env, msg(MINT)); run(env, cb("buy:1")); run(env, cb("go")); env.mk.bal = 4000
    run(env, msg(MINT)); a = run(env, cb("sell:50")); assert "Confirm" in texts(a)
    r = run(env, cb("go")); assert "Sold 50%" in texts(r)
    sw = [c for c in env.sg.calls if c["op"] == "swap"][-1]; assert sw["side"] == "sell" and sw["amount"] == 2000
    assert env.db.positions(UID)[0]["cost_lamports"] == LAMPORTS // 4
    run(env, msg(MINT)); run(env, cb("sell:100")); run(env, cb("go")); assert env.db.positions(UID) == []


def test_sell_without_holdings_or_bad_pct(env):
    start(env); run(env, msg(MINT)); run(env, cb("sell:50")); assert "hold this token" in texts(run(env, cb("go")))
    run(env, msg(MINT)); assert run(env, cb("sell:77"))[0]["op"] == "answer" and len(run(env, cb("sell:77"))) == 1


def test_positions_pnl_is_unrealized_and_honest(env):
    start(env); assert "No open positions" in texts(run(env, cb("positions")))
    run(env, msg(MINT)); run(env, cb("buy:1")); run(env, cb("go")); env.mk.bal = 500 * LAMPORTS; env.mk.sell_ratio = 1.0
    t = texts(run(env, cb("positions"))); assert "$TST" in t and "unrealized" in t and "%)" in t
    env.mk.route = False; assert "no sell route" in texts(run(env, cb("positions")))


def test_callback_forgery_without_state_is_harmless(env):
    start(env)
    for d in ("go", "buy:0", "buy:c", "sell:100", "buy:99", "buy:-1", "sell:", "tok"): assert all(a["op"] == "answer" for a in run(env, cb(d))), d
    assert [c for c in env.sg.calls if c["op"] == "swap"] == []


def test_state_belongs_to_user(env):
    start(env); run(env, msg(MINT)); run(env, cb("buy:0"))
    other = {"callback_query": {"id": "c", "from": {"id": 7}, "data": "go", "message": {"message_id": 5, "chat": {"id": 7, "type": "private"}}}}
    env.handle(other); assert [c for c in env.sg.calls if c["op"] == "swap"] == []
