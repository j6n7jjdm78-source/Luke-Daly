# tradebot

Multi-user Telegram trading bot (custodial). **Status: development. Do not use with real user funds.**
Network defaults to devnet; trading is off at two independent layers: `tradebot/config.json` (`mainnet_enabled`) and the signer's
`signer.json` (`trading_enabled`). Both must be turned on deliberately.

## Pieces
- `signer.py` – the only process with the master key. Verifies PIN, withdrawal policy, swap instructions (allow-list + simulation) itself.
- `app.py` – Telegram UI. Holds no keys or PIN hashes. `trade.py` builds quotes/previews; the signer decides.
- `swap_guard.py` – refuses any instruction not explicitly allowed; checks balance changes after simulating.

## Known limits (read before launch)
- The signer cannot tell a malicious token from a good one: a compromised app could make PIN-free buys of junk up to each user's caps.
- `min_out` is supplied by the app (bounded by the slippage cap); the signer does not fetch its own quote.
- Token/SOL amounts in receipts are simulation estimates; Positions reads the real balance.
- A buy that never confirms keeps its fee marked `settled=2` (in-tx, unconfirmed); reconcile on-chain, never re-send.
- Not reviewed by an independent security auditor. Custody of other people's funds may require licensing in your jurisdiction.

## Emergency
Pause everything (server): `sudo -u tradebot-signer touch /var/lib/tradebot-signer/PAUSE`
Resume: `python3 -m tradebot.signer resume` as the signer user. Unfreeze a user: `python3 -m tradebot.signer unfreeze <tg_id>`.
