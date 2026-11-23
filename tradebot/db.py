"""SQLite store (swap for Postgres later). Parameterized queries only. Secrets are only ever the encrypted blob from keystore."""
import json, sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, tg_id INTEGER UNIQUE NOT NULL, created REAL, frozen INTEGER DEFAULT 0,
  pin_hash TEXT, pin_state TEXT DEFAULT '{}', referrer_id INTEGER);
CREATE TABLE IF NOT EXISTS wallets(user_id INTEGER PRIMARY KEY REFERENCES users(id), pubkey TEXT UNIQUE NOT NULL, blob TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS withdraw_addresses(user_id INTEGER, address TEXT, added_at REAL, PRIMARY KEY(user_id, address));
CREATE TABLE IF NOT EXISTS withdrawals(id INTEGER PRIMARY KEY, user_id INTEGER, dest TEXT, lamports INTEGER, ts REAL, sig TEXT);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY, ts REAL, user_id INTEGER, event TEXT, detail TEXT);
"""


class DB:
    def __init__(self, path=":memory:"):
        self.c = sqlite3.connect(path); self.c.row_factory = sqlite3.Row
        self.c.executescript(SCHEMA)

    def audit(self, user_id, event, detail, now):
        self.c.execute("INSERT INTO audit_log(ts,user_id,event,detail) VALUES(?,?,?,?)", (now, user_id, event, json.dumps(detail)[:2000]))
        self.c.commit()

    def create_user(self, tg_id, now, referrer_id=None):
        self.c.execute("INSERT OR IGNORE INTO users(tg_id,created,referrer_id) VALUES(?,?,?)", (tg_id, now, referrer_id)); self.c.commit()
        return self.c.execute("SELECT id FROM users WHERE tg_id=?", (tg_id,)).fetchone()["id"]

    def user(self, user_id):
        return self.c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    def add_wallet(self, user_id, pubkey, blob):
        self.c.execute("INSERT INTO wallets(user_id,pubkey,blob) VALUES(?,?,?)", (user_id, pubkey, blob)); self.c.commit()

    def wallet(self, user_id):
        return self.c.execute("SELECT pubkey, blob FROM wallets WHERE user_id=?", (user_id,)).fetchone()

    def set_pin(self, user_id, pin_hash):
        self.c.execute("UPDATE users SET pin_hash=?, pin_state='{}' WHERE id=?", (pin_hash, user_id)); self.c.commit()

    def save_pin_state(self, user_id, state):
        self.c.execute("UPDATE users SET pin_state=? WHERE id=?", (json.dumps(state), user_id)); self.c.commit()

    def freeze(self, user_id, frozen=True):
        self.c.execute("UPDATE users SET frozen=? WHERE id=?", (1 if frozen else 0, user_id)); self.c.commit()

    def add_address(self, user_id, address, now):
        self.c.execute("INSERT OR IGNORE INTO withdraw_addresses(user_id,address,added_at) VALUES(?,?,?)", (user_id, address, now)); self.c.commit()

    def whitelist(self, user_id):
        return {r["address"]: r["added_at"] for r in self.c.execute("SELECT address, added_at FROM withdraw_addresses WHERE user_id=?", (user_id,))}

    def record_withdrawal(self, user_id, dest, lamports, now, sig=None):
        self.c.execute("INSERT INTO withdrawals(user_id,dest,lamports,ts,sig) VALUES(?,?,?,?,?)", (user_id, dest, lamports, now, sig)); self.c.commit()

    def withdrawn_since(self, user_id, since):
        return self.c.execute("SELECT COALESCE(SUM(lamports),0) s FROM withdrawals WHERE user_id=? AND ts>=?", (user_id, since)).fetchone()["s"]
