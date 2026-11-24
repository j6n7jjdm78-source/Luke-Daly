#!/usr/bin/env bash
# Saves the X login (re-encrypted) and the bot's state to main. Safe to run any time.
# The bot is the ONLY writer of these files (the workflow queues runs one at a time), so its copy always wins: no merging, no rebase.
# Each try: fetch main, set the bot's files aside, move to the latest main, put the files back, commit, push. Never leaves a half-done merge.
set -u
FILES="calls.csv state/tokens.enc state/watch.json state/candidates.csv state/liqmax.json state/scoreboard-* state/lesson-* state/lesson_idx state/recap-* state/growth-* state/mk* state/nr_* state/xspend-*"
TOK=~/.config/cliperz-bot/tokens.json; START=~/.config/cliperz-bot/tokens.start.sha
if [ -s "$TOK" ]; then
  if [ -f "$START" ] && [ "$(sha256sum "$TOK" | cut -d' ' -f1)" = "$(cat "$START")" ]; then
    # this run never refreshed the login: leave state/tokens.enc as it is on main (someone may have re-authorized it meanwhile)
    FILES="${FILES/state\/tokens.enc /}"
  elif ! openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:TOKEN_KEY -in state/tokens.enc 2>/dev/null | cmp -s - "$TOK"; then
    # the login changed (a refresh): re-encrypt it (a fresh salt would otherwise make every save a new commit)
    openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:TOKEN_KEY -in "$TOK" -out state/tokens.enc.new && mv state/tokens.enc.new state/tokens.enc
  fi
fi
git config user.name "cliperz-bot"; git config user.email "cliperz-bot@users.noreply.github.com"
for attempt in 1 2 3 4; do
  if ! git fetch -q origin main; then sleep $((attempt * 3)); continue; fi
  TMP="$(mktemp -d)"
  for f in $FILES; do [ -f "$f" ] && { mkdir -p "$TMP/$(dirname "$f")"; cp -p "$f" "$TMP/$f"; }; done
  git rebase --abort 2>/dev/null || true; git merge --abort 2>/dev/null || true
  git reset -q --hard origin/main
  cp -pR "$TMP"/. . 2>/dev/null || true
  rm -rf "$TMP"
  for f in $FILES; do [ -f "$f" ] && git add -f -- "$f"; done
  if git diff --cached --quiet; then exit 0; fi          # nothing changed
  git commit -q -m "bot state"
  if git push -q origin HEAD:main; then exit 0; fi
  sleep $((attempt * 3))
done
echo "save_state: could not push after 4 tries"
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_OWNER_CHAT_ID:-}" ]; then
  curl -s -m 20 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" -d "chat_id=${TELEGRAM_OWNER_CHAT_ID}" \
    --data-urlencode "text=⚠️ The bot could not save its state to GitHub after 4 tries. Calls and the X login may be lost if this repeats." >/dev/null || true
fi
exit 0
