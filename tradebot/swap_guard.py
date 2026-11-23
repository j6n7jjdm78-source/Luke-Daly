"""Signer-side validation of swap instructions supplied by the (untrusted) app. Pure functions, fail closed.
Static rules (program allowlist, instruction types, who may move what) + post-simulation balance invariants.
Anything not explicitly allowed is refused."""
import base64
import struct
from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
ATA_PROG = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
SYSTEM = "11111111111111111111111111111111"
COMPUTE = "ComputeBudget111111111111111111111111111111"
JUPITER = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
WSOL = "So11111111111111111111111111111111111111112"
MAX_IX, MAX_ACCTS, MAX_DATA = 24, 64, 1232
BASE_FEE = 10_000                      # generous allowance for signature fees
ATA_RENT = 2_039_280


class Refuse(Exception):
    pass


def pk(s, what="key"):
    try:
        k = Pubkey.from_string(s)
    except Exception:
        raise Refuse(f"bad {what}")
    return k


def ata(owner, mint, token=TOKEN):
    return Pubkey.find_program_address([bytes(pk(owner)), bytes(pk(token)), bytes(pk(mint))], pk(ATA_PROG))[0]


def parse_ix(d):
    if not isinstance(d, dict) or not isinstance(d.get("accounts"), list) or len(d["accounts"]) > MAX_ACCTS:
        raise Refuse("malformed instruction")
    try:
        data = base64.b64decode(d.get("data", ""), validate=True)
    except Exception:
        raise Refuse("bad instruction data")
    if len(data) > MAX_DATA:
        raise Refuse("instruction too large")
    metas = []
    for a in d["accounts"]:
        if not isinstance(a, dict) or not isinstance(a.get("isSigner"), bool) or not isinstance(a.get("isWritable"), bool):
            raise Refuse("malformed account meta")
        metas.append(AccountMeta(pk(a.get("pubkey"), "account"), a["isSigner"], a["isWritable"]))
    return Instruction(pk(d.get("programId"), "program"), data, metas)


def collect(jup):
    """Ordered (kind, ix_dict) list from Jupiter's /swap-instructions response. Unknown/extra sections are refused."""
    if not isinstance(jup, dict):
        raise Refuse("malformed swap data")
    if jup.get("tokenLedgerInstruction"):
        raise Refuse("token ledger not allowed")
    if jup.get("otherInstructions"):
        raise Refuse("other instructions not allowed")          # e.g. tip transfers
    sw = jup.get("swapInstruction")
    if not sw:
        raise Refuse("no swap instruction")
    out = [("compute", x) for x in (jup.get("computeBudgetInstructions") or [])]
    out += [("setup", x) for x in (jup.get("setupInstructions") or [])]
    out.append(("swap", sw))
    if jup.get("cleanupInstruction"):
        out.append(("cleanup", jup["cleanupInstruction"]))
    if len(out) > MAX_IX:
        raise Refuse("too many instructions")
    return out


def validate(user, side, mint, net_in, jup, cfg=None):
    """Returns (instructions, priority_fee_lamports). side 'buy': net_in = lamports going into the swap. side 'sell': net_in unused (0).
    Every rule below is allow-list: if it isn't listed it is refused."""
    cfg = cfg or {}
    u, m = pk(user, "wallet"), pk(mint, "mint")
    if side not in ("buy", "sell"):
        raise Refuse("bad side")
    if mint == WSOL or mint == user:
        raise Refuse("bad mint")
    jup_prog = cfg.get("jupiter_program", JUPITER)
    ata_m, ata_w = ata(user, mint), ata(user, WSOL)
    own_token_accts = {str(ata_m), str(ata_w)}
    max_priority = cfg.get("max_priority_fee_lamports", 5_000_000)
    ixs, priority, units, price, n_swap = [], 0, 200_000, 0, 0
    for kind, raw in collect(jup):
        ix = parse_ix(raw); prog = str(ix.program_id); data = bytes(ix.data); accts = ix.accounts
        for a in accts:
            if a.is_signer and a.pubkey != u:
                raise Refuse("foreign signer")
        if prog == COMPUTE:
            if kind != "compute": raise Refuse("compute budget out of place")
            if data[:1] == b"\x02" and len(data) == 5: units = struct.unpack("<I", data[1:])[0]
            elif data[:1] == b"\x03" and len(data) == 9: price = struct.unpack("<Q", data[1:])[0]
            else: raise Refuse("compute budget instruction not allowed")
        elif prog == SYSTEM:
            if kind != "setup" or side != "buy" or len(data) != 12 or struct.unpack("<I", data[:4])[0] != 2 or len(accts) != 2:
                raise Refuse("system instruction not allowed")
            lamports = struct.unpack("<Q", data[4:])[0]
            if accts[0].pubkey != u or accts[1].pubkey != ata_w or lamports > net_in:
                raise Refuse("system transfer not to own wrapped-SOL account")
        elif prog == TOKEN:
            if kind not in ("setup", "cleanup"): raise Refuse("token instruction out of place")
            if data == b"\x11" and len(accts) == 1 and str(accts[0].pubkey) == str(ata_w):          # SyncNative
                pass
            elif data == b"\x09" and len(accts) == 3 and str(accts[0].pubkey) in own_token_accts and accts[1].pubkey == u \
                    and accts[2].pubkey == u and accts[2].is_signer:                                    # CloseAccount -> user only
                pass
            else:
                raise Refuse("token instruction not allowed (transfer/approve/authority changes are refused)")
        elif prog == ATA_PROG:
            if kind != "setup" or data not in (b"", b"\x01") or len(accts) != 6: raise Refuse("ata instruction not allowed")
            payer, a, owner, mnt, sysp, tokp = [x.pubkey for x in accts]
            if payer != u or owner != u or str(mnt) not in (mint, WSOL) or str(sysp) != SYSTEM or str(tokp) != TOKEN or a != ata(user, str(mnt)):
                raise Refuse("ata creation not for own wallet")
        elif prog == jup_prog:
            if kind != "swap": raise Refuse("swap out of place")
            n_swap += 1
            if any(a.pubkey == u and a.is_writable for a in accts):
                raise Refuse("swap would write to the wallet account")
            if not any(a.pubkey == u and a.is_signer for a in accts):
                raise Refuse("swap does not use the wallet as authority")
        else:
            raise Refuse("program not allowed")
        ixs.append(ix)
    if n_swap != 1:
        raise Refuse("expected exactly one swap")
    priority = units * price // 1_000_000
    if units > 1_400_000 or priority > max_priority:
        raise Refuse("priority fee too high")
    return ixs, priority


# ---------- balances ----------
def parse_snapshot(accounts, user, mint):
    """accounts: getMultipleAccounts(jsonParsed) 'value' list for [wallet, ata(mint), ata(WSOL)]. Returns {'sol','tokens':{mint:int},'eff_sol'}."""
    if not isinstance(accounts, list) or len(accounts) != 3:
        raise Refuse("bad account snapshot")
    def amt(a, want_mint):
        if not a: return 0
        try:
            info = a["data"]["parsed"]["info"]
            if info["owner"] != user or info["mint"] != want_mint: raise Refuse("token account not owned by wallet")
            return int(info["tokenAmount"]["amount"])
        except (KeyError, TypeError, ValueError):
            raise Refuse("bad token account")
    sol = int((accounts[0] or {}).get("lamports", 0))
    t, w = amt(accounts[1], mint), amt(accounts[2], WSOL)
    return {"sol": sol, "tokens": {mint: t}, "wsol": w, "eff_sol": sol + w}


def check_simulation(side, mint, pre, post, gross_in, amount_in, min_out, priority, rent_allowance=2 * ATA_RENT):
    """Balance invariants after simulating the exact transaction. Returns sol_gain for sells (used for the fee), 0 for buys."""
    d_sol = post["eff_sol"] - pre["eff_sol"]
    d_tok = post["tokens"][mint] - pre["tokens"][mint]
    slack = priority + BASE_FEE
    if side == "buy":
        if d_sol < -(gross_in + slack + rent_allowance):
            raise Refuse("simulation: wallet would lose more SOL than the trade amount")
        if d_tok < min_out or min_out <= 0:
            raise Refuse("simulation: tokens received below the minimum")
        return 0
    if d_tok < -amount_in:
        raise Refuse("simulation: would spend more tokens than requested")
    if d_sol < min_out - slack or min_out <= 0:
        raise Refuse("simulation: SOL received below the minimum")
    return max(d_sol, 0)
