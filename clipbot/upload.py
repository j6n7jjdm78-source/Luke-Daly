"""Upload to YouTube via the Data API v3 (OAuth, resumable)."""
from __future__ import annotations

from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",      # comments, search
    "https://www.googleapis.com/auth/yt-analytics.readonly",  # retention stats
]


def _creds(cfg: dict):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    
    tok = Path(cfg["token"])
    creds = Credentials.from_authorized_user_file(tok, SCOPES) if tok.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(cfg["client_secret"], SCOPES)
            creds = flow.run_local_server(port=0)
        tok.write_text(creds.to_json())
    return creds


def _service(cfg: dict):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=_creds(cfg))


def analytics_service(cfg: dict):
    from googleapiclient.discovery import build
    return build("youtubeAnalytics", "v2", credentials=_creds(cfg))


def first_comment(video_id: str, text: str, cfg: dict) -> None:
    """Post a top-level comment (the API cannot pin it; pin manually in Studio)."""
    _service(cfg).commentThreads().insert(part="snippet", body={"snippet": {
        "videoId": video_id,
        "topLevelComment": {"snippet": {"textOriginal": text}}}}).execute()


def upload(path: Path, title: str, description: str, cfg: dict,
           publish_at: str | None = None) -> str:
    from googleapiclient.http import MediaFileUpload

    body = {
        "snippet": {
            "title": title[:100],
            "description": (description + "\n\n#Shorts")[:5000],
            "tags": cfg.get("tags", []) + ["Shorts"],
            "categoryId": cfg.get("category_id", "22"),
        },
        "status": {"privacyStatus": cfg.get("privacy", "private"),
                   "selfDeclaredMadeForKids": False},
    }
    if publish_at:  # scheduled publish requires private + publishAt
        body["status"].update(privacyStatus="private", publishAt=publish_at)
    req = _service(cfg).videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(str(path), mimetype="video/mp4", resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]
