"""Symbols and settings. Edit SYMBOLS to match your broker's names in MT5."""
import os
from dataclasses import dataclass, field


@dataclass
class Symbol:
    name: str          # label used in alerts
    mt5: str           # symbol name in your MetaTrader terminal (brokers differ: XAUUSD, XAUUSDm, BTCUSD...)
    binance: str = ""  # fallback feed (BTC/ETH)
    kraken: str = ""   # public feed (BTC/ETH), works from cloud servers
    yahoo: str = ""    # fallback feed (gold futures)
    label: str = ""    # shown in messages, e.g. BTCUSD
    style: str = "btc"  # message style: "gold" (Pro Trader layout) or "btc" (Grand Pips layout)
    pip: float = 1.0   # price units per pip
    decimals: int = 0  # price decimals shown
    pct: bool = True   # True: sl/tp1/step/zone_cap/run are fractions of price; False: absolute price units
    sl: float = 0.0062        # stop distance beyond the far edge of the zone
    tp1: float = 0.0078       # TP1 distance beyond the near edge of the zone
    step: float = 0.0038      # gap between TPs
    zone_cap: float = 0.0095  # max entry-zone width
    run: float = 0.0039       # profit that triggers the "trade active and running" update


SYMBOLS = [
    # GOLD: 50-pip layout (pip = 0.10): SL 5.0 beyond the zone, TP1-TP3 5.0 apart, TP4 = Hold
    Symbol("GOLD", mt5="XAUUSD", yahoo="GC=F", label="GOLD", style="gold", pip=0.10, decimals=0,
           pct=False, sl=5.0, tp1=5.0, step=5.0, zone_cap=10.0, run=2.5),
    # BTC / ETH: wider levels as a share of price (scaled from the Grand Pips BTC example)
    Symbol("BTC", mt5="BTCUSD", binance="BTCUSDT", kraken="XBTUSD", label="BTCUSD", style="btc", pip=10.0, decimals=0),
    Symbol("ETH", mt5="ETHUSD", binance="ETHUSDT", kraken="ETHUSD", label="ETHUSD", style="btc", pip=1.0, decimals=1),
]


def get_symbol(name):
    return next(x for x in SYMBOLS if x.name == name)


@dataclass
class Settings:
    timeframe: str = "15m"         # entry timeframe (trend checked on 15m + 1h)
    htf: str = "1h"                # higher timeframe: trend + main S/R levels
    poll_seconds: int = 60
    min_touches: int = 3           # pivot touches needed for a level to count as S/R
    cooldown_bars: int = 6         # don't repeat same-direction signal within N bars
    source: str = os.getenv("DATA_SOURCE", "auto")  # auto | mt5 | public
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat: str = os.getenv("TELEGRAM_CHAT_ID", "")
    log_file: str = "signals.csv"
    symbols: list = field(default_factory=lambda: SYMBOLS)
