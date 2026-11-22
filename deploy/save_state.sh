#!/usr/bin/env bash
# Saves the X login (re-encrypted) and the bot's state back to the repo. Safe to run any time.
set -u
if [ -s ~/.config/cliperz-bot/tokens.json ]; then
  openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:TOKEN_KEY -in ~/.config/cliperz-bot/tokens.json -out state/tokens.enc.new && mv state/tokens.enc.new state/tokens.enc
fi
git config user.name "cliperz-bot"; git config user.email "cliperz-bot@users.noreply.github.com"
git add calls.csv state/tokens.enc state/watch.json state/candidates.csv state/scoreboard-* state/liqmax.json state/lesson-* state/lesson_idx state/recap-* state/growth-* 2>/dev/null || true
if ! git diff --cached --quiet; then
  git commit -q -m "bot state"
  git pull --rebase -q 2>/dev/null || git rebase --abort 2>/dev/null || true
  git push -q || true
fi
