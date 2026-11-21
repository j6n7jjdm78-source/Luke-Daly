#!/bin/bash
# Starts the Cliperz bot loop whenever a cloud session starts, resumes or compacts. Safe to run any number of times.
set -euo pipefail

# Only in a Claude Code cloud session
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"
mkdir -p state drafts

# Kill switch: a file named STOP means "do not run"
if [ -f STOP ]; then
  exit 0
fi

# Nothing to install: the card renderer's browser is built into the cloud image.
# Start the bot only if it is not already running (idempotent).
if ! pgrep -f "bot/run_loop.py" >/dev/null 2>&1; then
  setsid nohup python3 bot/run_loop.py >> state/bot.log 2>&1 < /dev/null &
fi
exit 0
