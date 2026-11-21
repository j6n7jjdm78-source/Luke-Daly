# clipbot

YouTube live stream (VOD) → auto-picked highlights → 9:16 captioned clips → YouTube Shorts.

Pipeline: `yt-dlp` download → `faster-whisper` word-level transcript → Claude picks the best
20–59s moments → `ffmpeg` renders 1080x1920 with burned-in captions → YouTube Data API upload.

## Setup
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
The stream must have ended (VOD available). Tune everything in `config.yaml`.

## Notes
- Only clip streams you own or have permission to reuse. Re-uploading others' content risks
  copyright strikes. Uploads default to `private` so you can review first.
- API quota: an upload costs 1,600 units of the default 10,000/day (~6 uploads/day).
  Projects not passed through Google's API audit have uploads locked to private.
- `state.json` prevents re-uploading the same clip.
- Tests: `pytest tests`
