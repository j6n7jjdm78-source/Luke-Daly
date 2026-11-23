#!/usr/bin/env bash
# One-shot laptop setup: ./scripts/setup.sh
set -e
cd "$(dirname "$0")/.."
miss=0
if ! command -v ffmpeg >/dev/null; then
  echo "ffmpeg missing: install with 'brew install ffmpeg' (mac) or 'sudo apt install ffmpeg' (linux) or 'winget install ffmpeg' (windows)"; miss=1
fi
command -v python3 >/dev/null || { echo "python3 (3.10+) missing"; miss=1; }
[ $miss = 1 ] && exit 1
python3 -m venv .venv
. .venv/bin/activate
pip install -q -U pip
pip install -q -r requirements.txt pytest
[ -f .env ] || { cp .env.example .env; echo "Created .env - add your ANTHROPIC_API_KEY"; }
echo "Done. Next: source .venv/bin/activate && python -m clipbot --doctor"
