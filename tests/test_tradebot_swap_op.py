import copy, json, os
import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature
from solders.transaction import VersionedTransaction
from tradebot import swap_guard as g
from tradebot.keystore import Keystore
from tradebot.signer import Signer
from tradebot.signer_db import SignerDB
import test_tradebot_swap_guard as F       # reuse instruction fixtures (USER differs: we rebuild for the signer's wallet)

T = [1_000_000.0]; FEE_WALLET = str(Keypair().pubkey()); BH = str(Keypair().pubkey()); PIN = "483920"
SOL = 10 ** 9


class RPC:
    def __init__(self): self.sent, self.pre, self.post, self.sim_err, self.fail_send_after = [], None, None, None, None; self.confirmed = True
    def get_balance(self, pk): return 5 * SOL
    def get_blockhash(self): return BH
    def get_accounts(self, keys): return self.pre
    def get_alt(self, k): raise AssertionError("no alt expected")
    def simulate(self, tx, keys): return {"err": self.sim_err, "accounts": self.post}
    def confirm(self, sig): return self.confirmed
    def send(self, tx):
        if self.fail_send_after is not None and len(self.sent) >= self.fail_send_after: raise RuntimeError("rpc down")
        self.sent.append(tx); return "SIG%d" % len(self.sent)


def acct(mint, owner, amt): return {"data": {"parsed": {"info": {"mint": mint, "owner": owner, "tokenAmount": {"amount": str(amt)}}}}}


class Env:
    def __init__(self, tmp):
        T[0] = 1_000_000.0; self.rpc = RPC(); self.db = SignerDB(":memory:")
        self.s = Signer(Keystore(bytes(range(32))), self.db, self.rpc, str(tmp / "PAUSE"), clock=lambda: T[0],
                        cfg={"fee_wallet": FEE_WALLET, "fee_bps": 100, "trading_enabled": True})
        r = self.s.handle({"op": "create_wallet", "tg_id": 1}); self.user = r["pubkey"]
        self.mint = str(Keypair().pubkey()); self.ata_m, self.ata_w = str(g.ata(self.user, self.mint)), str(g.ata(self.user, g.WSOL))
        self.set_state(10 * SOL, 0, 10 * SOL - 4_000_000, 1000)
        self.s.handle({"op": "set_pin", "tg_id": 1, "pin": PIN})

    def set_state(self, sol, tok, post_sol, post_tok, wsol=0):
        self.pre = [{"lamports": sol}, acct(self.mint, self.user, tok) if tok else None, None]
        self.rpc.pre = self.pre
        self.rpc.post = [{"lamports": post_sol}, acct(self.mint, self.user, post_tok), None]

    def jup(self, side="buy", net=None):
        U, M, AM, AW = self.user, self.mint, self.ata_m, self.ata_w
        net = net if net is not None else 99 * SOL // 100
        sw = F.ix(g.JUPITER, [F.am(g.TOKEN), F.am(U, True, False), F.am(AW, False, True), F.am(AM, False, True)], b"\x01")
        if side == "buy":
            return {"computeBudgetInstructions": F.cb(), "otherInstructions": [], "setupInstructions": [
                F.create(U, AM, U, M), F.create(U, AW, U, g.WSOL), F.transfer(U, AW, net), F.sync(AW)],
                "swapInstruction": sw, "cleanupInstruction": F.close(AW, U, U), "addressLookupTableAddresses": []}
        return {"computeBudgetInstructions": F.cb(), "otherInstructions": [], "setupInstructions": [F.create(U, AW, U, g.WSOL)],
                "swapInstruction": sw, "cleanupInstruction": F.close(AW, U, U)}

    def swap(self, side="buy", amount=SOL, jup=None, **kw):
        req = {"op": "swap", "tg_id": 1, "side": side, "mint": self.mint, "amount": amount, "min_out": 900, "quote_out": 1000,
               "slippage_bps": 500, "jup": jup if jup is not None else self.jup(side, amount - amount // 100)}
        req.update(kw); return self.s.handle(req)


@pytest.fixture
def e(tmp_path): return Env(tmp_path)


def test_buy_builds_signed_tx_with_fee_first(e):
    e.set_state(10 * SOL, 0, 10 * SOL - SOL // 2 - 4_000_000, 1000)
    r = e.swap(amount=SOL // 2); assert r["ok"] and r["fee_lamports"] == SOL // 200 and r["confirmed"]
    tx = VersionedTransaction.from_bytes(e.rpc.sent[0]); msg = tx.message
    keys = [str(k) for k in msg.account_keys]; assert keys[0] == e.user and FEE_WALLET in keys           # fee wallet is in the tx
    first = msg.instructions[0]; assert str(msg.account_keys[first.program_id_index]) == g.SYSTEM          # fee transfer is instruction 0
    import struct; assert struct.unpack("<IQ", bytes(first.data)) == (2, SOL // 200)
    from solders.message import to_bytes_versioned
    assert tx.signatures[0].verify(Pubkey.from_string(e.user), to_bytes_versioned(msg))                    # signature really verifies
    assert e.db.c.execute("SELECT fee, settled FROM fee_ledger").fetchone()[:] == (SOL // 200, 1)


def test_buy_refusals(e):
    e.set_state(10 * SOL, 0, 9 * SOL, 1000)
    r = e.swap(amount=SOL); assert not r["ok"] and "PIN" in r["error"]                       # above the PIN-free size, no PIN given
    r = e.swap(amount=SOL, pin="000111"); assert not r["ok"] and "wrong PIN" in r["error"]    # wrong PIN
    r = e.swap(amount=2 * SOL, pin=PIN); assert not r["ok"] and "per-trade" in r["error"]     # above per-trade cap even with the PIN
    assert e.rpc.sent == []


def test_jup_attack_refused_end_to_end(e):
    j = e.jup("buy", 99 * SOL // 100 // 2); j["setupInstructions"].append(F.transfer(e.user, F.ATTACKER, 1))
    r = e.swap(amount=SOL // 2, jup=j); assert not r["ok"] and e.rpc.sent == []
    assert e.db.c.execute("SELECT COUNT(*) FROM audit WHERE event='swap_refused'").fetchone()[0] == 1


def test_simulation_catches_hidden_loss_and_errors(e):
    e.set_state(10 * SOL, 0, 5 * SOL, 1000)                                              # tx would take 5 SOL on a 0.5 SOL trade
    assert not e.swap(amount=SOL // 2)["ok"] and e.rpc.sent == []
    e.set_state(10 * SOL, 0, 9 * SOL, 1000); e.rpc.sim_err = {"InstructionError": [0, "x"]}
    assert not e.swap(amount=SOL // 2)["ok"] and e.rpc.sent == []
    e.rpc.sim_err = None; e.set_state(10 * SOL, 0, 9 * SOL, 10)                          # too few tokens vs min_out 900
    assert not e.swap(amount=SOL // 2)["ok"] and e.rpc.sent == []


def test_slippage_and_min_out_rules(e):
    e.set_state(10 * SOL, 0, 9 * SOL, 1000)
    assert not e.swap(amount=SOL // 2, slippage_bps=5000)["ok"]
    assert not e.swap(amount=SOL // 2, min_out=1)["ok"]                                  # min_out far below quote - cap
    assert not e.swap(amount=SOL // 2, min_out=0)["ok"]
    assert e.rpc.sent == []


def good_buy_state(e, amt=SOL // 2): e.set_state(10 * SOL, 0, 10 * SOL - amt - 4_000_000, 1000)


def test_daily_cap(e):
    e.s.handle({"op": "set_limits", "tg_id": 1, "limits": {"daily": SOL}})
    good_buy_state(e); assert e.swap(amount=SOL // 2)["ok"]
    good_buy_state(e); assert e.swap(amount=SOL // 2)["ok"]
    good_buy_state(e); r = e.swap(amount=SOL // 2); assert not r["ok"] and "daily" in r["error"]
    T[0] += 86401; good_buy_state(e); assert e.swap(amount=SOL // 2)["ok"]                   # window rolls over


def test_hourly_cap(e):
    e.s.handle({"op": "set_limits", "tg_id": 1, "limits": {"hourly": 1}})
    good_buy_state(e); assert e.swap(amount=SOL // 2)["ok"]
    good_buy_state(e); r = e.swap(amount=SOL // 2); assert not r["ok"] and "hourly" in r["error"]
    T[0] += 3601; good_buy_state(e); assert e.swap(amount=SOL // 2)["ok"]


def test_limit_changes_lower_free_raise_needs_pin_and_waits(e):
    cur = e.s.handle({"op": "get_limits", "tg_id": 1})["limits"]
    assert e.s.handle({"op": "set_limits", "tg_id": 1, "limits": {"max_trade": cur["max_trade"] // 2}})["ok"]
    assert not e.s.handle({"op": "set_limits", "tg_id": 1, "limits": {"max_trade": SOL}})["ok"]                  # raise without PIN
    r = e.s.handle({"op": "set_limits", "tg_id": 1, "pin": PIN, "limits": {"max_trade": SOL}}); assert r["ok"] and r["pending"]
    assert e.s.handle({"op": "get_limits", "tg_id": 1})["limits"]["max_trade"] == cur["max_trade"] // 2         # not yet
    T[0] += 86401; assert e.s.handle({"op": "get_limits", "tg_id": 1})["limits"]["max_trade"] == SOL            # after cooldown
    for bad in ({"max_trade": 10 ** 12}, {"nope": 1}, {}, "x", {"max_trade": -1}, {"max_trade": True}):
        assert not e.s.handle({"op": "set_limits", "tg_id": 1, "pin": PIN, "limits": bad})["ok"]


def test_sell_flow_and_fee_settlement(e):
    e.set_state(SOL, 5000, SOL + 2 * 10 ** 8, 0)
    r = e.swap("sell", amount=5000, min_out=10 ** 8, quote_out=10 ** 8, slippage_bps=500, jup=e.jup("sell")); assert r["ok"], r
    assert r["fee_lamports"] == 2 * 10 ** 6 and len(e.rpc.sent) == 2                      # swap tx + separate fee tx
    assert e.db.c.execute("SELECT fee, settled FROM fee_ledger").fetchone()[:] == (2 * 10 ** 6, 1)


def test_sell_requires_holdings_and_sim_ok(e):
    e.set_state(SOL, 100, SOL + 2 * 10 ** 8, 0)
    assert "tokens" in e.swap("sell", amount=5000, min_out=10 ** 8, quote_out=10 ** 8, jup=e.jup("sell"))["error"]
    e.set_state(SOL, 5000, SOL + 1000, 0)                                                   # receives almost no SOL
    assert not e.swap("sell", amount=5000, min_out=10 ** 8, quote_out=10 ** 8, jup=e.jup("sell"))["ok"] and e.rpc.sent == []


def test_failed_fee_is_recorded_owed_and_retried(e):
    e.set_state(SOL, 5000, SOL + 2 * 10 ** 8, 0); e.rpc.fail_send_after = 1                 # swap goes through, fee tx fails
    r = e.swap("sell", amount=5000, min_out=10 ** 8, quote_out=10 ** 8, jup=e.jup("sell")); assert r["ok"]
    assert e.db.c.execute("SELECT settled FROM fee_ledger").fetchone()[0] == 0
    e.rpc.fail_send_after = None; e.set_state(SOL, 5000, SOL + 2 * 10 ** 8, 0)
    e.swap("sell", amount=5000, min_out=10 ** 8, quote_out=10 ** 8, jup=e.jup("sell"))
    assert [r[0] for r in e.db.c.execute("SELECT settled FROM fee_ledger ORDER BY id")] == [1, 1]   # old owed fee retried


def test_paused_frozen_unconfigured_and_hostile(e, tmp_path):
    good_buy_state(e)
    e.s.handle({"op": "admin_pause"}); assert not e.swap(amount=SOL // 2)["ok"]; os.unlink(e.s.pause_file)
    e.s.cfg = {"trading_enabled": True}; assert "not configured" in e.swap(amount=SOL // 2)["error"]; e.s.cfg = {"fee_wallet": FEE_WALLET, "trading_enabled": True}
    e.s.handle({"op": "admin_freeze", "tg_id": 1}); r = e.swap(amount=SOL // 2); assert not r["ok"] and "frozen" in r["error"]; e.db.set_frozen(1, False)
    for kw in ({"side": "hold"}, {"mint": "x"}, {"amount": 0}, {"amount": True}, {"amount": "5"}, {"min_out": -1}, {"slippage_bps": 0},
               {"slippage_bps": 10 ** 9}, {"jup": None}, {"jup": []}, {"jup": {"swapInstruction": 1}}, {"mint": e.user}, {"mint": g.WSOL}):
        if kw.get("amount") == "5" or "jup" in kw:
            req = {"op": "swap", "tg_id": 1, "side": "buy", "mint": e.mint, "amount": "5" if "amount" in kw else SOL // 2, "min_out": 900,
                   "quote_out": 1000, "slippage_bps": 500, "jup": kw["jup"] if "jup" in kw else e.jup()}
            assert e.s.handle(req)["ok"] is False, kw; continue
        r = e.swap(amount=SOL // 2, **kw) if "amount" not in kw else e.swap(**kw); assert r["ok"] is False, kw
    assert e.rpc.sent == []


def test_trading_is_off_unless_explicitly_enabled(e):
    good_buy_state(e)
    e.s.cfg = {"fee_wallet": FEE_WALLET}                                   # enabled flag missing -> refused
    r = e.swap(amount=SOL // 2); assert not r["ok"] and "disabled" in r["error"] and e.rpc.sent == []
    e.s.cfg = {"fee_wallet": FEE_WALLET, "trading_enabled": False}; assert not e.swap(amount=SOL // 2)["ok"]
    e.s.cfg = {"fee_wallet": FEE_WALLET, "trading_enabled": True}; assert e.swap(amount=SOL // 2)["ok"]


def test_unconfirmed_buy_fee_is_never_resent(e):
    good_buy_state(e); e.rpc.confirmed = False
    assert e.swap(amount=SOL // 2)["ok"]
    assert e.db.c.execute("SELECT settled FROM fee_ledger").fetchone()[0] == 2
    e.rpc.confirmed = True; good_buy_state(e); e.swap(amount=SOL // 2)
    assert len(e.rpc.sent) == 2                                             # only the two swap txs; no separate fee tx was sent for the unconfirmed one
