# Windows PC setup (paper only, MT5 DEMO account)

Everything here runs on your Windows PC. The bot refuses to start unless MT5 reports a DEMO account.

## One-time setup (about 15 minutes)
1. Install **Python 3.11 (64-bit)** from python.org (tick "Add to PATH"). The MetaTrader5 package needs 64-bit Windows Python.
2. Install **MetaTrader 5** and open a **demo** account (File > Open an Account > MetaQuotes-Demo, EUR, 100, leverage 1:100 or lower). Keep MT5 open and logged in. In Tools > Options > Expert Advisors, tick "Allow algorithmic trading".
3. In a terminal: `pip install MetaTrader5`
4. Get this repo: `git clone` it (or `git pull` if you have it), then `git checkout claude/exciting-ramanujan-wrm2hn`.
5. Open `gold\config.json`. Confirm `symbol` matches the name in your Market Watch (XAUUSD or GOLD). Leave `utc_offset_hours` as `null` to auto-detect, or set it (e.g. 2 or 3) if the bot says it cannot detect it.

## Step 1: get real XAUUSD history and backtest it
```
py gold\mt5_export.py
py gold\lab.py xauusd
```
Read `first-check-results.md` rules: no verdict under 50 out-of-sample trades; compare against the random baseline; results on demo data are optimistic.

## Step 2: run the paper bot (only if step 1 looks sensible)
```
py gold\paper_bot.py
```
Or double-click `run_bot.bat` to auto-restart after a crash. It exits for good (code 2) after 3 straight errors or a kill switch, and writes `gold\alerts.log` and `incidents.md`.
- Every trade is written to `data\live_trades.csv` (fills come from MT5, nothing is guessed).
- Shield blocks any order whose stop risk exceeds `risk_pct` of the balance, a wide spread, a stale feed, trading outside 07:00-16:00 UTC, the daily loss limit, the loss streak, 10 trades a day, and anything inside `gold\news_blackouts.txt`.
- Optional `gold\news_blackouts.txt`: one line per window, UTC, e.g. `2026-12-10T13:00:00,2026-12-10T14:00:00` (CPI, FOMC, jobs).
- To start on boot: Task Scheduler > create task > trigger "At log on" > action: run `run_bot.bat`.

## Tested vs NOT tested
- Tested here (Linux, saved gold-proxy candles): signal logic, Shield rules, kill switch, missing-stop close, error halt, journaling, state file. Run `python3 gold/test_bot.py`.
- Smoke-tested only with a stand-in MT5 module: the MT5 calls (connect, rates, order_send, positions, close, demo-only refusal).
- NOT tested against real MT5: actual fills, filling mode acceptance, stop-level rejects, deal history mapping, offset auto-detect, symbol name. Watch the first trades by hand in MT5 and tell me anything that looks wrong.

## Stop it any time
Close the terminal window, or close any position by hand in MT5. Nothing here touches a real-money account.
