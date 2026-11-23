import base64, copy, struct
import pytest
from solders.keypair import Keypair
from tradebot import swap_guard as g

USER = str(Keypair().pubkey()); MINT = str(Keypair().pubkey()); ATTACKER = str(Keypair().pubkey()); OTHER = str(Keypair().pubkey())
ATA_M, ATA_W = str(g.ata(USER, MINT)), str(g.ata(USER, g.WSOL))
NET = 990_000_000


def b64(b): return base64.b64encode(bytes(b)).decode()
def am(k, s=False, w=False): return {"pubkey": k, "isSigner": s, "isWritable": w}
def ix(prog, accts, data=b""): return {"programId": prog, "accounts": accts, "data": b64(data)}
def transfer(frm, to, lam): return ix(g.SYSTEM, [am(frm, True, True), am(to, False, True)], struct.pack("<IQ", 2, lam))
def sync(a): return ix(g.TOKEN, [am(a, False, True)], b"\x11")
def close(a, dest, owner): return ix(g.TOKEN, [am(a, False, True), am(dest, False, True), am(owner, True)], b"\x09")
def create(payer, a, owner, mint): return ix(g.ATA_PROG, [am(payer, True, True), am(a, False, True), am(owner), am(mint), am(g.SYSTEM), am(g.TOKEN)], b"\x01")
def swap(extra=()): return ix(g.JUPITER, [am(g.TOKEN), am(USER, True, False), am(ATA_W, False, True), am(ATA_M, False, True), *extra], b"\x01\x02\x03")
def cb(units=200_000, price=1000): return [ix(g.COMPUTE, [], b"\x02" + struct.pack("<I", units)), ix(g.COMPUTE, [], b"\x03" + struct.pack("<Q", price))]


def good_buy():
    return {"computeBudgetInstructions": cb(), "otherInstructions": [], "setupInstructions": [
        create(USER, ATA_M, USER, MINT), create(USER, ATA_W, USER, g.WSOL), transfer(USER, ATA_W, NET), sync(ATA_W)],
        "swapInstruction": swap(), "cleanupInstruction": close(ATA_W, USER, USER), "addressLookupTableAddresses": []}


def good_sell():
    return {"computeBudgetInstructions": cb(), "otherInstructions": [], "setupInstructions": [create(USER, ATA_W, USER, g.WSOL)],
            "swapInstruction": swap(), "cleanupInstruction": close(ATA_W, USER, USER)}


_D = object()
def ok_buy(j=_D): return g.validate(USER, "buy", MINT, NET, good_buy() if j is _D else j)
def ok_sell(j=_D): return g.validate(USER, "sell", MINT, 0, good_sell() if j is _D else j)


def test_valid_buy_and_sell_pass():
    ixs, pri = ok_buy(); assert len(ixs) == 8 and pri == 200_000 * 1000 // 1_000_000
    assert len(ok_sell()[0]) == 5


def mutate(fn, base=good_buy):
    j = copy.deepcopy(base()); fn(j); return j


ATTACKS = {
    "extra transfer to attacker":        lambda j: j["setupInstructions"].append(transfer(USER, ATTACKER, 1)),
    "transfer to attacker instead of wsol": lambda j: j["setupInstructions"].__setitem__(2, transfer(USER, ATTACKER, NET)),
    "transfer more than net":            lambda j: j["setupInstructions"].__setitem__(2, transfer(USER, ATA_W, NET + 1)),
    "transfer from other wallet":        lambda j: j["setupInstructions"].__setitem__(2, transfer(OTHER, ATA_W, 1)),
    "system create account":             lambda j: j["setupInstructions"].append(ix(g.SYSTEM, [am(USER, True, True), am(OTHER, True, True)], struct.pack("<IQQ", 0, 1, 1) + bytes(40))),
    "system assign":                     lambda j: j["setupInstructions"].append(ix(g.SYSTEM, [am(USER, True, True)], struct.pack("<I", 1) + bytes(32))),
    "unknown program":                   lambda j: j["setupInstructions"].append(ix(OTHER, [am(USER, True, True)], b"\x00")),
    "token transfer":                    lambda j: j["setupInstructions"].append(ix(g.TOKEN, [am(ATA_M, False, True), am(ATTACKER, False, True), am(USER, True)], b"\x03" + bytes(8))),
    "token approve":                     lambda j: j["setupInstructions"].append(ix(g.TOKEN, [am(ATA_M, False, True), am(ATTACKER), am(USER, True)], b"\x04" + bytes(8))),
    "token set authority":               lambda j: j["setupInstructions"].append(ix(g.TOKEN, [am(ATA_M, False, True), am(USER, True)], b"\x06\x02\x01" + bytes(32))),
    "close to attacker":                 lambda j: j.__setitem__("cleanupInstruction", close(ATA_W, ATTACKER, USER)),
    "close foreign account":             lambda j: j.__setitem__("cleanupInstruction", close(OTHER, USER, USER)),
    "close with foreign owner":          lambda j: j.__setitem__("cleanupInstruction", close(ATA_W, USER, OTHER)),
    "sync native on foreign account":    lambda j: j["setupInstructions"].append(sync(OTHER)),
    "ata create for attacker owner":     lambda j: j["setupInstructions"].append(create(USER, str(g.ata(ATTACKER, MINT)), ATTACKER, MINT)),
    "ata create wrong address":          lambda j: j["setupInstructions"].append(create(USER, OTHER, USER, MINT)),
    "ata create other mint":             lambda j: j["setupInstructions"].append(create(USER, str(g.ata(USER, OTHER)), USER, OTHER)),
    "ata paid by other payer":           lambda j: j["setupInstructions"].append(create(OTHER, ATA_M, USER, MINT)),
    "jito tip in other instructions":    lambda j: j.__setitem__("otherInstructions", [transfer(USER, ATTACKER, 1000)]),
    "token ledger":                      lambda j: j.__setitem__("tokenLedgerInstruction", swap()),
    "swap writes the wallet":            lambda j: j.__setitem__("swapInstruction", ix(g.JUPITER, [am(USER, True, True)], b"\x01")),
    "swap without wallet authority":     lambda j: j.__setitem__("swapInstruction", ix(g.JUPITER, [am(ATA_W, False, True)], b"\x01")),
    "foreign signer in swap":            lambda j: j.__setitem__("swapInstruction", swap([am(OTHER, True, True)])),
    "no swap":                           lambda j: j.__setitem__("swapInstruction", None),
    "two swaps":                         lambda j: j["setupInstructions"].append(swap()),
    "swap in setup slot":                lambda j: (j["setupInstructions"].append(j["swapInstruction"]), j.__setitem__("swapInstruction", swap())),
    "huge priority fee":                 lambda j: j.__setitem__("computeBudgetInstructions", cb(1_400_000, 10 ** 9)),
    "compute budget other tag":          lambda j: j["computeBudgetInstructions"].append(ix(g.COMPUTE, [], b"\x00" + bytes(8))),
    "compute budget in wrong slot":      lambda j: j["setupInstructions"].append(cb()[0]),
    "bad base64":                        lambda j: j["setupInstructions"].append({"programId": g.TOKEN, "accounts": [], "data": "!!!"}),
    "bad pubkey":                        lambda j: j["setupInstructions"].append(ix("nope", [])),
    "meta not bool":                     lambda j: j["setupInstructions"].append(ix(g.TOKEN, [{"pubkey": USER, "isSigner": 1, "isWritable": 0}], b"\x11")),
    "oversized data":                    lambda j: j["setupInstructions"].append(ix(g.TOKEN, [], bytes(2000))),
    "too many instructions":             lambda j: j["setupInstructions"].extend([sync(ATA_W)] * 40),
}


@pytest.mark.parametrize("name", list(ATTACKS))
def test_attacks_refused(name):
    with pytest.raises(g.Refuse): ok_buy(mutate(ATTACKS[name]))


def test_sell_cannot_include_system_transfer():
    j = mutate(lambda j: j["setupInstructions"].append(transfer(USER, ATA_W, 1)), good_sell)
    with pytest.raises(g.Refuse): ok_sell(j)


def test_non_dict_and_bad_inputs():
    for bad in (None, [], "x", 5, {}, {"swapInstruction": 5}):
        with pytest.raises(g.Refuse): ok_buy(bad)
    with pytest.raises(g.Refuse): g.validate(USER, "hold", MINT, NET, good_buy())
    with pytest.raises(g.Refuse): g.validate(USER, "buy", g.WSOL, NET, good_buy())
    with pytest.raises(g.Refuse): g.validate("bad", "buy", MINT, NET, good_buy())


def snap(sol, tok, wsol=0): return {"sol": sol, "tokens": {MINT: tok}, "wsol": wsol, "eff_sol": sol + wsol}


def test_buy_simulation_invariants():
    pre = snap(5 * 10 ** 9, 0)
    g.check_simulation("buy", MINT, pre, snap(4 * 10 ** 9 - 10_000, 1000), 10 ** 9, NET, 900, 200)      # ok
    with pytest.raises(g.Refuse): g.check_simulation("buy", MINT, pre, snap(3 * 10 ** 9, 1000), 10 ** 9, NET, 900, 200)   # lost 2 SOL
    with pytest.raises(g.Refuse): g.check_simulation("buy", MINT, pre, snap(4 * 10 ** 9, 100), 10 ** 9, NET, 900, 200)    # too few tokens
    with pytest.raises(g.Refuse): g.check_simulation("buy", MINT, pre, snap(4 * 10 ** 9, 5000), 10 ** 9, NET, 0, 200)     # no min-out
    with pytest.raises(g.Refuse): g.check_simulation("buy", MINT, pre, snap(5 * 10 ** 9, 0), 10 ** 9, NET, 900, 200)      # nothing received


def test_sell_simulation_invariants():
    pre = snap(10 ** 9, 5000)
    gain = g.check_simulation("sell", MINT, pre, snap(10 ** 9 + 2 * 10 ** 8, 0), 0, 5000, 10 ** 8, 200); assert gain == 2 * 10 ** 8
    with pytest.raises(g.Refuse): g.check_simulation("sell", MINT, pre, snap(10 ** 9 + 2 * 10 ** 8, -1), 0, 5000, 10 ** 8, 200)   # sells more than asked
    with pytest.raises(g.Refuse): g.check_simulation("sell", MINT, pre, snap(10 ** 9 + 10 ** 7, 0), 0, 5000, 10 ** 8, 200)        # too little SOL
    with pytest.raises(g.Refuse): g.check_simulation("sell", MINT, pre, snap(10 ** 9 - 10 ** 8, 0), 0, 5000, 10 ** 8, 200)        # loses SOL


def test_wsol_counts_as_sol_and_snapshot_parsing():
    acct = lambda mint, owner, amt: {"data": {"parsed": {"info": {"mint": mint, "owner": owner, "tokenAmount": {"amount": str(amt)}}}}}
    s = g.parse_snapshot([{"lamports": 100}, acct(MINT, USER, 7), acct(g.WSOL, USER, 50)], USER, MINT)
    assert s["eff_sol"] == 150 and s["tokens"][MINT] == 7
    assert g.parse_snapshot([None, None, None], USER, MINT)["eff_sol"] == 0
    for bad in (None, [], [None, None], [{"lamports": 1}, acct(MINT, ATTACKER, 7), None], [{"lamports": 1}, acct(OTHER, USER, 7), None],
                [{"lamports": 1}, {"data": {}}, None]):
        with pytest.raises(g.Refuse): g.parse_snapshot(bad, USER, MINT)
