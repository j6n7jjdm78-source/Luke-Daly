"""Non-secret app store: users, referrals, audit. No keys, no PIN hashes, no whitelist: the app process can never read those."""
import json, sqlite3


class AppDB:
    def __init__(self, path=":memory:"):
        self.c = sqlite3.connect(path, check_same_thread=False); self.c.row_factory = sqlite3.Row
        self.c.executescript("""
CREATE TABLE IF NOT EXISTS users(tg_id INTEGER PRIMARY KEY, created REAL, referrer INTEGER, pubkey TEXT, last_balance INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS positions(tg_id INTEGER, mint TEXT, symbol TEXT, cost_lamports INTEGER, PRIMARY KEY(tg_id, mint));
CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY, tg_id INTEGER, ts REAL, side TEXT, mint TEXT, symbol TEXT, lamports INTEGER, tokens INTEGER, fee INTEGER, sig TEXT, estimated INTEGER);
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

    def record_trade(self, tg_id, now, side, mint, symbol, lamports, tokens, fee, sig, estimated=True):
        self.c.execute("INSERT INTO trades(tg_id,ts,side,mint,symbol,lamports,tokens,fee,sig,estimated) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (tg_id, now, side, mint, symbol, int(lamports), int(tokens), int(fee), sig, 1 if estimated else 0)); self.c.commit()

    def add_cost(self, tg_id, mint, symbol, lamports):
        self.c.execute("INSERT INTO positions(tg_id,mint,symbol,cost_lamports) VALUES(?,?,?,?) ON CONFLICT(tg_id,mint) DO UPDATE SET "
                       "cost_lamports=cost_lamports+excluded.cost_lamports, symbol=excluded.symbol", (tg_id, mint, symbol, int(lamports))); self.c.commit()

    def reduce_cost(self, tg_id, mint, numer, denom):
        r = self.c.execute("SELECT cost_lamports FROM positions WHERE tg_id=? AND mint=?", (tg_id, mint)).fetchone()
        if not r: return
        left = r["cost_lamports"] - (r["cost_lamports"] * numer // max(denom, 1)) if numer < denom else 0
        if left <= 0: self.c.execute("DELETE FROM positions WHERE tg_id=? AND mint=?", (tg_id, mint))
        else: self.c.execute("UPDATE positions SET cost_lamports=? WHERE tg_id=? AND mint=?", (left, tg_id, mint))
        self.c.commit()

    def positions(self, tg_id):
        return self.c.execute("SELECT mint, symbol, cost_lamports FROM positions WHERE tg_id=?", (tg_id,)).fetchall()
