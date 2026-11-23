"""Secret-bearing store. Owned and readable ONLY by the signer's OS user. The app process never opens this file."""
import json, sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS wallets(tg_id INTEGER PRIMARY KEY, pubkey TEXT UNIQUE NOT NULL, blob TEXT NOT NULL,
  pin_hash TEXT, pin_state TEXT DEFAULT '{}', frozen INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS whitelist(tg_id INTEGER, address TEXT, added_at REAL, PRIMARY KEY(tg_id, address));
CREATE TABLE IF NOT EXISTS withdrawals(id INTEGER PRIMARY KEY, tg_id INTEGER, dest TEXT, lamports INTEGER, ts REAL, sig TEXT);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts REAL, tg_id INTEGER, event TEXT, detail TEXT);
"""


class SignerDB:
    def __init__(self, path=":memory:"):
        self.c = sqlite3.connect(path, check_same_thread=False); self.c.row_factory = sqlite3.Row
        self.c.executescript(SCHEMA)

    def audit(self, tg_id, event, detail, now):
        self.c.execute("INSERT INTO audit(ts,tg_id,event,detail) VALUES(?,?,?,?)", (now, tg_id, event, json.dumps(detail, default=str)[:1000])); self.c.commit()

    def wallet(self, tg_id):
        return self.c.execute("SELECT * FROM wallets WHERE tg_id=?", (tg_id,)).fetchone()

    def add_wallet(self, tg_id, pubkey, blob):
        self.c.execute("INSERT INTO wallets(tg_id,pubkey,blob) VALUES(?,?,?)", (tg_id, pubkey, blob)); self.c.commit()

    def set_pin(self, tg_id, pin_hash):
        self.c.execute("UPDATE wallets SET pin_hash=?, pin_state='{}' WHERE tg_id=?", (pin_hash, tg_id)); self.c.commit()

    def save_pin_state(self, tg_id, state):
        self.c.execute("UPDATE wallets SET pin_state=? WHERE tg_id=?", (json.dumps(state), tg_id)); self.c.commit()

    def set_frozen(self, tg_id, frozen):
        self.c.execute("UPDATE wallets SET frozen=? WHERE tg_id=?", (1 if frozen else 0, tg_id)); self.c.commit()

    def add_address(self, tg_id, address, now):
        self.c.execute("INSERT OR IGNORE INTO whitelist(tg_id,address,added_at) VALUES(?,?,?)", (tg_id, address, now)); self.c.commit()

    def whitelist(self, tg_id):
        return {r["address"]: r["added_at"] for r in self.c.execute("SELECT address, added_at FROM whitelist WHERE tg_id=?", (tg_id,))}

    def record_withdrawal(self, tg_id, dest, lamports, now, sig):
        self.c.execute("INSERT INTO withdrawals(tg_id,dest,lamports,ts,sig) VALUES(?,?,?,?,?)", (tg_id, dest, lamports, now, sig)); self.c.commit()

    def withdrawn_since(self, tg_id, since):
        return self.c.execute("SELECT COALESCE(SUM(lamports),0) s FROM withdrawals WHERE tg_id=? AND ts>=?", (tg_id, since)).fetchone()["s"]


SCHEMA2 = """
CREATE TABLE IF NOT EXISTS limits(tg_id INTEGER PRIMARY KEY, max_trade INTEGER, daily INTEGER, hourly INTEGER, pin_free INTEGER, pending TEXT, effective_at REAL);
CREATE TABLE IF NOT EXISTS swaps(id INTEGER PRIMARY KEY, tg_id INTEGER, ts REAL, side TEXT, mint TEXT, volume INTEGER, sig TEXT);
CREATE TABLE IF NOT EXISTS fee_ledger(id INTEGER PRIMARY KEY, tg_id INTEGER, ts REAL, side TEXT, mint TEXT, volume INTEGER, fee INTEGER, sig TEXT, settled INTEGER);
"""


def _init2(self): self.c.executescript(SCHEMA2)


_orig_init = SignerDB.__init__
def _init(self, path=":memory:"):
    _orig_init(self, path); _init2(self)
SignerDB.__init__ = _init


def limits_row(self, tg_id): return self.c.execute("SELECT * FROM limits WHERE tg_id=?", (tg_id,)).fetchone()
def save_limits(self, tg_id, vals, pending, effective_at):
    self.c.execute("INSERT INTO limits(tg_id,max_trade,daily,hourly,pin_free,pending,effective_at) VALUES(?,?,?,?,?,?,?) "
                   "ON CONFLICT(tg_id) DO UPDATE SET max_trade=excluded.max_trade, daily=excluded.daily, hourly=excluded.hourly, "
                   "pin_free=excluded.pin_free, pending=excluded.pending, effective_at=excluded.effective_at",
                   (tg_id, vals["max_trade"], vals["daily"], vals["hourly"], vals["pin_free"], json.dumps(pending) if pending else None, effective_at))
    self.c.commit()
def record_swap(self, tg_id, now, side, mint, volume, sig):
    self.c.execute("INSERT INTO swaps(tg_id,ts,side,mint,volume,sig) VALUES(?,?,?,?,?,?)", (tg_id, now, side, mint, volume, sig)); self.c.commit()
def volume_since(self, tg_id, since, side="buy"):
    return self.c.execute("SELECT COALESCE(SUM(volume),0) s FROM swaps WHERE tg_id=? AND ts>=? AND side=?", (tg_id, since, side)).fetchone()["s"]
def swaps_since(self, tg_id, since):
    return self.c.execute("SELECT COUNT(*) n FROM swaps WHERE tg_id=? AND ts>=?", (tg_id, since)).fetchone()["n"]
def add_fee(self, tg_id, now, side, mint, volume, fee, sig, settled):
    self.c.execute("INSERT INTO fee_ledger(tg_id,ts,side,mint,volume,fee,sig,settled) VALUES(?,?,?,?,?,?,?,?)", (tg_id, now, side, mint, volume, fee, sig, 1 if settled else 0)); self.c.commit()
def owed_fees(self, tg_id): return self.c.execute("SELECT id, fee FROM fee_ledger WHERE tg_id=? AND settled=0 ORDER BY id LIMIT 3", (tg_id,)).fetchall()
def settle_fee(self, fee_id, sig):
    self.c.execute("UPDATE fee_ledger SET settled=1, sig=? WHERE id=?", (sig, fee_id)); self.c.commit()


for _f in (limits_row, save_limits, record_swap, volume_since, swaps_since, add_fee, owed_fees, settle_fee):
    setattr(SignerDB, _f.__name__, _f)
