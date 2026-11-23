"""Non-secret app store: users, referrals, audit. No keys, no PIN hashes, no whitelist: the app process can never read those."""
import json, sqlite3


class AppDB:
    def __init__(self, path=":memory:"):
        self.c = sqlite3.connect(path, check_same_thread=False); self.c.row_factory = sqlite3.Row
        self.c.executescript("""
CREATE TABLE IF NOT EXISTS users(tg_id INTEGER PRIMARY KEY, created REAL, referrer INTEGER, pubkey TEXT, last_balance INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts REAL, tg_id INTEGER, event TEXT, detail TEXT);""")

    def ensure_user(self, tg_id, now, pubkey=None, referrer=None):
        self.c.execute("INSERT OR IGNORE INTO users(tg_id,created,referrer,pubkey) VALUES(?,?,?,?)", (tg_id, now, referrer, pubkey))
        if pubkey: self.c.execute("UPDATE users SET pubkey=? WHERE tg_id=?", (pubkey, tg_id))
        self.c.commit()

    def user(self, tg_id):
        return self.c.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,)).fetchone()

    def set_balance(self, tg_id, lamports):
        self.c.execute("UPDATE users SET last_balance=? WHERE tg_id=?", (int(lamports), tg_id)); self.c.commit()

    def total_balance(self):
        return self.c.execute("SELECT COALESCE(SUM(last_balance),0) s FROM users").fetchone()["s"]

    def audit(self, tg_id, event, detail, now):
        self.c.execute("INSERT INTO audit(ts,tg_id,event,detail) VALUES(?,?,?,?)", (now, tg_id, event, json.dumps(detail, default=str)[:1000])); self.c.commit()
