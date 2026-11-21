"""Candle sources. Each returns a DataFrame indexed by UTC time with open/high/low/close/volume."""
import sys
import pandas as pd
import requests

TF_MINUTES = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
COLS = ["open", "high", "low", "close", "volume"]


def _mt5_tf(mt5, tf):
    return {"5m": mt5.TIMEFRAME_M5, "15m": mt5.TIMEFRAME_M15, "30m": mt5.TIMEFRAME_M30,
            "1h": mt5.TIMEFRAME_H1, "4h": mt5.TIMEFRAME_H4, "1d": mt5.TIMEFRAME_D1}[tf]


class MT5Source:
    name = "MetaTrader5"

    def __init__(self, login=None, password=None, server=None):
        import MetaTrader5 as mt5  # only available on Windows
        self.mt5 = mt5
        kw = {}
        if login:
            kw = dict(login=int(login), password=password, server=server)
        if not mt5.initialize(**kw):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

    def candles(self, sym, tf, n=400):
        s = sym.mt5
        self.mt5.symbol_select(s, True)
        rates = self.mt5.copy_rates_from_pos(s, _mt5_tf(self.mt5, tf), 0, n)
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"No MT5 data for {s}: {self.mt5.last_error()}")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.rename(columns={"tick_volume": "volume"}).set_index("time")
        return df[COLS]


class PublicSource:
    """Works anywhere (Linux/Mac): Binance for BTC/ETH, Yahoo for gold futures."""
    name = "public (Kraken/Binance/Yahoo)"

    def candles(self, sym, tf, n=400):
        if sym.kraken:
            try:
                return self._kraken(sym.kraken, tf, n)
            except Exception as e:
                print(f"[info] kraken failed for {sym.name} ({e}); trying binance")
        if sym.binance:
            return self._binance(sym.binance, tf, n)
        if sym.yahoo:
            return self._yahoo(sym.yahoo, tf, n)
        raise RuntimeError(f"No public feed for {sym.name}")

    def _kraken(self, pair, tf, n):
        r = requests.get("https://api.kraken.com/0/public/OHLC",
                         params={"pair": pair, "interval": TF_MINUTES[tf]}, timeout=15)
        r.raise_for_status()
        j = r.json()
        if j.get("error"):
            raise RuntimeError(j["error"])
        rows = next(v for k, v in j["result"].items() if k != "last")
        df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"])
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df.set_index("time")[COLS].astype(float).tail(n)

    def _binance(self, pair, tf, n):
        r = requests.get("https://api.binance.com/api/v3/klines",
                         params={"symbol": pair, "interval": tf, "limit": n}, timeout=15)
        r.raise_for_status()
        df = pd.DataFrame(r.json()).iloc[:, :6]
        df.columns = ["time"] + COLS
        df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
        return df.set_index("time").astype(float)

    def _yahoo(self, ticker, tf, n):
        base = {"1h": "60m", "4h": "60m", "30m": "30m", "15m": "15m", "5m": "5m", "1d": "1d"}[tf]
        r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                         params={"interval": base, "range": "60d" if base != "1d" else "2y"},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        q = res["indicators"]["quote"][0]
        df = pd.DataFrame(q, index=pd.to_datetime(res["timestamp"], unit="s", utc=True))
        df = df[COLS].dropna()
        if tf == "4h":  # Yahoo has no 4h bars: resample from 1h
            df = df.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                        "close": "last", "volume": "sum"}).dropna()
        return df.tail(n)


def make_source(settings, env):
    if settings.source in ("auto", "mt5") and sys.platform == "win32":
        try:
            return MT5Source(env.get("MT5_LOGIN"), env.get("MT5_PASSWORD"), env.get("MT5_SERVER"))
        except Exception as e:
            if settings.source == "mt5":
                raise
            print(f"[warn] MT5 unavailable ({e}); using public feeds")
    elif settings.source == "mt5":
        raise RuntimeError("The MetaTrader5 Python package only runs on Windows.")
    return PublicSource()
