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
