# Cliperz bot: runbook

How the bot runs, how to check it, and what to do when something breaks. Keep this file up to date when behaviour changes.

## How it runs
- **Only on GitHub Actions** (`.github/workflows/bot.yml`). A run starts about every 5 minutes, stays alive about 45 minutes and runs `python3 bot/bot.py` back to back (one scan cycle takes roughly 10-90 seconds). Runs queue one behind another (concurrency group `cliperz-bot`), so two never post at once.
- **Never run a second copy anywhere else.** The X login uses a single-use refresh token; two copies break it. `bot/bot.py` refuses to run outside GitHub (set `CLIPERZ_ALLOW_LOCAL=1` only when deliberately moving to a private server, and then stop the GitHub schedule first). The Claude session-start hook is a no-op for the same reason.
- **Stages each cycle** (`bot/bot.py`, bottom): track open calls -> call out (normal tier) -> early tier -> candidate outcome tracking -> weekly board (Sundays) -> daily recap (21:00 UTC) -> daily lesson (14:00 UTC) -> growth DM (16:00 UTC) -> Telegram button taps -> marketing drafts (12:00 and 18:00 UTC) -> weekly outcome analysis (Sundays 18:00 UTC) -> scan DM (every 20 minutes).
- **State** is saved to `main` by `deploy/save_state.sh` as `bot state` commits: `calls.csv`, `state/tokens.enc` (encrypted X login), `state/candidates.csv`, `state/watch.json`, daily marks (`state/lesson-*`, `recap-*`, `growth-*`, `mk*`). The bot is the only writer; the script resets to the latest `main` and puts the bot's files on top, so there are no merge conflicts. If saving fails 4 times you get a Telegram DM.

## Safety rules the bot follows (do not weaken without a decision)
- A coin must pass the RugCheck gate (mint and freeze revoked, no "danger" flag, enough holders, low risk score). Early (new-pair) coins use slightly looser holder/score limits but the same hard blocks.
- Dump filter: skipped if more than 25% below its 1-hour high. Two-cycle confirmation before a call posts.
- Results are always labelled as **peaks after our call**; nothing is posted about failures; peaks above 100x are treated as bad data.
- The marketing agent only drafts. A post happens only when the owner taps **Post this** on a draft in Telegram (own tap only, once per draft, expires after 24 h, max 6 a day).
- No automatic replies, follows, likes or DMs to other users. No buying of called coins.

## Secrets (GitHub repo: Settings -> Secrets and variables -> Actions)
`CLIPERZ_X_CLIENT_ID` (34 chars), `CLIPERZ_X_CLIENT_SECRET` (50 chars), `CLIPERZ_TG_BOT_TOKEN`, `CLIPERZ_TG_CHAT_ID` (channel), `CLIPERZ_TG_OWNER_CHAT_ID` (private chat), `CLIPERZ_TOKEN_KEY` (encrypts `state/tokens.enc`). Paste values with no spaces or line breaks (the code strips them, but check anyway). Never put any of these in a file or chat.

## Checking health
- The **watchdog** (`.github/workflows/watchdog.yml`, every 30 minutes) DMs you at most every 2 hours if the bot looks stalled (no run active, stuck run, repeated failures, no state saved for 3 hours).
- The 20-minute **scan DM** shows candidates, near-misses and the last cycle's timing. The job log prints a `[TIMING]` line each cycle with GeckoTerminal request and rate-limit counts.
- Quick manual check: Actions tab -> `cliperz-bot` runs; recent `bot state` commits on `main`; the X login on `main` should be under about 2 hours old (the bot refreshes it itself).

## Common problems
| Symptom | Cause | Fix |
|---|---|---|
| DM "X login could not refresh (HTTP 401 ... Missing valid authorization header)" | X client id/secret in GitHub secrets is wrong | Re-add `CLIPERZ_X_CLIENT_ID` / `_SECRET` (OAuth 2.0 pair from the X developer portal) |
| DM "X login could not refresh (HTTP 400 ... token invalid)" | The refresh token was used up or revoked | Re-authorize once: `python3 bot/auth.py`, open the link while logged in as the account, paste the callback URL; encrypt the new `tokens.json` into `state/tokens.enc` with `CLIPERZ_TOKEN_KEY` and merge it; cancel the running job and start a clean run |
| DM "could not save its state after 4 tries" | GitHub or network problem during a save | Check the run log; it retries every save, so one DM is usually transient |
| Posts stop, no DMs | Run chain broken or paused | Watchdog will DM; otherwise start a run: Actions -> cliperz-bot -> Run workflow -> mode `run` |
| Card upload fails (401) | X login problem (see above) | Same as the 401/400 rows |
| GeckoTerminal rate limited (many 429 in `[TIMING]`) | Free-tier limit on shared GitHub IPs | Normal; trending lists are cached 5 minutes. A keyed data provider would remove it |

## Operating the bot
- **Stop everything:** commit a file named `STOP` to `main` (the loop checks it each cycle), or disable the workflow in the Actions tab.
- **Restart cleanly after a merge:** cancel the in-progress run, then Actions -> cliperz-bot -> Run workflow (branch `main`, mode `run`). A dispatched run first syncs to the latest `main`.
- **Test mode:** Run workflow with mode `test` logs in to X and sends a Telegram DM without posting anything public. Mode `check` only verifies the secrets exist.
- **Thresholds** live in `bot/config.json` (liquidity, market cap, buy ratio, dump filter, confirmation time, early tier on/off, `marketing_buttons`). Change them in a PR.
- **Tests:** `python3 -m pytest tests/test_cliperz_bot.py tests/test_watchdog.py -q` (also runs on every pull request). Add a test whenever a bug is fixed.
- **Dry run on a dev machine:** `CLIPERZ_DRY=1 python3 bot/scan_report.py` prints what a scan finds and posts nothing.

## Known limits
- GeckoTerminal rate-limits GitHub's shared IPs; scans slow down when it does.
- The early tier (new pairs) has weak results so far (see the weekly outcome DM); review `early_enabled` after a week of data.
- Follower count is tiny; no tactic here replaces useful, consistent content and the owner's own engagement.
