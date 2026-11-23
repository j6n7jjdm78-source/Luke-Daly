# clipbot

YouTube live stream (VOD) → auto-picked highlights → 9:16 captioned clips → YouTube Shorts.

Pipeline: `yt-dlp` download → `faster-whisper` word-level transcript → Claude picks the best
short (12–35s) hook-first moments → `ffmpeg` renders 1080x1920 with burned-in captions → YouTube Data API upload.

## Setup (laptop)
```bash
./scripts/setup.sh                 # venv + deps; creates .env
python -m clipbot --doctor         # preflight: shows anything still missing
```
Manual steps:
```bash
sudo apt install ffmpeg            # or brew install ffmpeg
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
```
YouTube upload: create a Google Cloud project, enable **YouTube Data API v3**, create an
OAuth *Desktop* client, save it as `client_secret.json`. First upload opens a browser login.

## Use
```bash
python -m clipbot https://www.youtube.com/watch?v=VIDEO_ID --no-upload   # render only, review in output/
python -m clipbot https://www.youtube.com/watch?v=VIDEO_ID               # render + upload
```
Works on streams that are **live now** (records in 10-min chunks and clips as it goes) or **ended within the last 24h** (older ones are refused). Tune everything in `config.yaml`.

## Notes
- Only clip streams you own or have permission to reuse. Re-uploading others' content risks
  copyright strikes. Uploads default to `private` so you can review first.
- API quota: an upload costs 1,600 units of the default 10,000/day (~6 uploads/day).
  Projects not passed through Google's API audit have uploads locked to private.
- `state.json` prevents re-uploading the same clip.
- Tests: `pytest tests`

## Growth loop
- **Schedule**: `upload.schedule` spreads clips over daily slots (default 4/day) using YouTube scheduled publishing.
- **First comment**: posted automatically (the API can't pin it; pin in Studio).
- **Analyst**: `python -m clipbot --analyze` pulls retention stats into `insights.json`; the best/worst past Shorts are fed into the clip-selection prompt on the next run.
- Re-run the OAuth login once after updating (new scopes: comments + analytics).

## Safety & credit
- `rights_confirmed` in `config.yaml` must be `true` before any upload. Only set it for streams you own or have permission to clip.
- Every clip gets a small `@creator` watermark and `Source: @creator - <url>` in the description. Credit is good practice but is **not** a licence; get the creator's OK for streams that aren't yours.
- Live chunks overlap (`source.overlap_seconds`) so moments spanning a chunk boundary aren't cut; clips are de-duplicated by absolute stream time.
