# Trading Team Plan (paper only)

Built from the 5 interview answers. Status: PLAN ONLY. Nothing is connected, no keys exist, no orders can be placed.

## Your answers
1. Markets: Gold (XAUUSD) and BTC (BTCUSD). Timeframes: 5m, 15m, 1h. Style: support and resistance.
2. Goal: paper trading, 5 to 10 trades a day.
3. Screen time: watching charts and drawing support/resistance levels.
4. Account: EUR 100 paper. Risk per trade 3% (EUR 3). Goal 5% a day (EUR 5), treated as an aspiration, not a rule.
5. Broker: Vantage or PU Prime on MetaTrader (MT5). Both should offer demo accounts; confirm when you open one.

## Automation pick (1-5; higher hours = better, higher damage = worse, higher ease = easier)
| Job | Hours saved | Damage if wrong | Ease without code | Verdict |
|---|---|---|---|---|
| Scanning charts | 5 | 1 | 4 | Build first |
| Drawing S/R levels | 5 | 1 | 3 | Build with Scout |
| Backtesting ideas | 3 | 2 | 2 | Build second |
| Journaling | 3 | 1 | 5 | Build third |
| Executing trades | 2 | 5 | 2 | Last, paper only |

Pick: start with Scout (levels + scanning). It saves the most hours and cannot lose money. Execution comes last and stays on demo.

## Team (5 agents)
1. **Scout** watches XAUUSD and BTCUSD on 5m/15m/1h, keeps a daily list of support/resistance levels, and flags touches, rejections and breaks that match the rules.
2. **Lab** backtests each rule on real data with spread, fees and slippage, and checks minimum lot size against EUR 3 risk.
3. **Shield** checks size, stop, spread and daily limits on every order and can halt the bot.
4. **Pilot** sends orders to the MT5 DEMO account only, after Shield approves.
5. **Journal** logs each trade with reason and result, and writes the weekly review.
Plus the **Coordinator**, the only agent you talk to.

## Agent cards

### Scout
- Job: find support/resistance setups on gold and BTC.
- Reads: price candles (5m, 15m, 1h) from the broker demo feed, with timestamps.
- Outputs: today's level list; alerts "market, timeframe, level, setup type, entry idea, stop idea".
- Runs: levels refreshed at 00:00 UTC and each new 1h close; scans every closed 5m bar.
- Tools: MT5 data, TradingView alerts.
- Never: places orders, moves levels mid-trade, or uses data without a timestamp.
- Prompt: "You are Scout. Every day mark the strongest support and resistance levels for XAUUSD and BTCUSD from the 1h chart, then confirm them on 15m. On each closed 5m bar, check whether price touched a level and rejected it or broke it with a close beyond it. Send one alert per setup with market, level, direction, suggested stop beyond the level, and the reason. Use only real candle data with timestamps. Never place or change orders. If data is missing or stale, say so and stop alerting."

### Lab
- Job: prove or reject each rule before it trades.
- Reads: historical candles, spread and fee data.
- Outputs: a backtest report per rule: return, max drawdown, trade count, worst case, after costs.
- Runs: when a new rule is proposed, then weekly.
- Never: reports a result without costs, calls anything "proven", or invents numbers.
- Prompt: "You are Lab. Test each rule on at least 12 months of real data including a losing period. Include spread, commission and slippage on every trade. Test on one period and confirm on a later unseen period. Report trades, return, max drawdown and the worst day, in EUR and in R. Check that the stop distance allows the broker's minimum lot at EUR 3 risk and count how many setups are skipped for that reason. Fewer than 50 out-of-sample trades means no verdict. Label estimates."

### Shield
- Job: approve or block every order.
- Reads: order request, account balance, open positions, spread, news calendar.
- Outputs: APPROVED or BLOCKED with the reason.
- Never: lets an order through without a stop, raises risk, or overrides a limit.
- Prompt: "You are Shield. Approve an order only if: a stop is set; risk is at most the configured percent of balance; lot size respects the broker minimum and step; spread is below the limit; the data feed is under 2 minutes old; daily loss limit and loss-streak limit are not hit; no high-impact news within 30 minutes. Otherwise BLOCK and say why. At the daily loss limit, halt all new entries until the next UTC day."

### Pilot
- Job: place approved orders on the demo account.
- Reads: Shield-approved orders only.
- Outputs: fill confirmation or error, logged.
- Never: trades a real account, acts without Shield approval, removes or widens a stop, averages down.
- Prompt: "You are Pilot. Send an order to the MT5 DEMO account only after Shield says APPROVED. Confirm the account is demo before every order; if it is not, stop and alert. Set the stop with the order. On any error, read it, retry once, then alert the coordinator. Log every fill, cancel and error."

### Journal
- Job: record and review every trade.
- Reads: Pilot's fills, Scout's alert reason.
- Outputs: trade log; daily summary; weekly review (best/worst trade, what worked, what to change).
- Never: guesses a missing number; leaves a blank to be filled with an estimate.
- Prompt: "You are Journal. For every trade log id, market, timeframe, side, entry, stop, target, exit, fees, spread, P&L in EUR and R, the reason in and out. Leave blanks if data is missing. Every Sunday write a review: results per setup type, paper versus backtest, slippage versus assumption, and one rule to change."

### Coordinator
- Job: the only agent you talk to.
- Sends one daily message: market recap, what each agent did, open trades and P&L, anything Shield blocked, and the one decision needed from you.
- Never acts on a trade without your clear permission.

## Config (plain English; edit values here)
```
mode: PAPER (demo account only)
markets: XAUUSD, BTCUSD
timeframes: 5m, 15m, 1h
account_size_eur: 100
risk_per_trade: 3%          # EUR 3 at start
daily_loss_limit: 6%        # EUR 6, so two full losses stop the day
loss_streak_stop: 2         # stop after 2 straight losses
max_trades_per_day: 10
max_leverage: per broker demo, never above 5x effective
stop_required: yes
daily_goal: 5% (aspiration, never a reason to add risk)
news_pause_minutes: 30
data_max_age_minutes: 2
go_live: only when I type "go live" after the final check
```

## One-day plan
- Morning: open a Vantage or PU Prime DEMO account in EUR with MT5; check XAUUSD and BTCUSD contract specs (min lot, step, spread); install MT5; get Scout running and posting levels.
- Afternoon: Lab tests the first rule; Shield and Pilot connect to the demo account; Journal and Coordinator start; bot runs on paper.
- Evening: review what works, what doesn't, what is next.

## Stress tests (before 24/7)
Duplicate orders, missed stop, wrong position size, stale price feed, API timeout, timezone error, partial fill. For each: test, what happened, fix. Results go here after running.

## Final check (before any real money)
- Does every agent do one job?
- Can the bot place a trade you did not approve?
- Does it stop when the feed dies or the daily limit hits?
- Did every rule survive 2 weeks of paper trading after fees? (Recommend 4+ weeks and 50+ trades.)
- Would you understand every message without code?

## WHY THIS COULD FAIL
| Risk | Fix |
|---|---|
| EUR 3 risk is below the minimum lot for a normal gold/BTC stop, so most setups are skipped or oversized | Lab checks contract specs first; Shield blocks any order whose real risk exceeds EUR 3 |
| 5 to 10 trades a day on 5m charts: spread and commission may eat the edge | Lab tests with full costs; drop the 5m timeframe if it fails |
| 3% risk per trade is aggressive: a losing streak can empty the account fast | Daily limit 6%, stop after 2 losses; consider 1% |
| 5% a day goal pushes toward overtrading and bigger size | It is a measured outcome only, never a rule input |
| Support/resistance is subjective; the bot's levels may differ from yours | Define level rules in numbers (touches, lookback) and review 20 trades by hand |
| TradingView to MT5 needs a third-party bridge, and MT5 needs a Windows machine or VPS to run 24/7 | Choose the bridge/VPS on day 1; test restarts |
| AgenKit is an outside tool I cannot verify from here | Check it works as described before relying on it; the agent cards work in any agent builder |
| Demo fills are better than live fills | Treat paper results as optimistic until live-like slippage is modelled |
