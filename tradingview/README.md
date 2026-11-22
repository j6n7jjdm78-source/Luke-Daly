# TradingView version

`pips_central.pine` is the same strategy as the Python scanner, running on TradingView's servers.

## Install (phone or browser)
1. TradingView > Pine Editor > paste `pips_central.pine` > Save > Add to chart. Use a **15 minute** chart of GOLD, BTC and ETH.
2. In the indicator settings, set **Telegram chat id** to your channel id.
3. Create an alert on the indicator: Condition = the indicator, **Any alert() function call**.
   Notifications > **Webhook URL** = `https://api.telegram.org/bot<YOUR_TOKEN>/sendMessage`
4. Repeat for each symbol. Webhooks need a paid TradingView plan (Essential or higher).

The token lives only in the alert's webhook URL. Never paste it into the script.
