"""
Uploads videos to YouTube using the YouTube Data API v3.
Costs 100 quota units per upload (free quota: 10,000 units/day).

Authentication: OAuth 2.0 with refresh token.
Run setup_youtube_auth.py once to generate the token file.
"""
import os
import time
from pathlib import Path
from typing import Dict, Optional

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from src.utils.logger import get_logger
from src.utils.retry import with_retry

logger = get_logger("upload")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
YOUTUBE_API_SERVICE = "youtube"
YOUTUBE_API_VERSION = "v3"

# YouTube video categories
CATEGORY_MAP = {
    "technology": "28",
    "science": "28",
    "education": "27",
    "news": "25",
    "finance": "22",
    "business": "22",
    "entertainment": "24",
    "gaming": "20",
}


def _load_credentials(tokens_path: str, secrets_path: str) -> Credentials:
    """Load OAuth credentials, refreshing if expired."""
    creds = None

    if Path(tokens_path).exists():
        creds = Credentials.from_authorized_user_file(tokens_path, SCOPES)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_credentials(creds, tokens_path)
            logger.info("OAuth token refreshed successfully.")
        except RefreshError as exc:
            logger.warning("Token refresh failed: %s. Re-authenticating…", exc)
            creds = None

    if not creds or not creds.valid:
        if not Path(secrets_path).exists():
            raise FileNotFoundError(
                f"YouTube client secrets not found: {secrets_path}\n"
                "Run 'python setup_youtube_auth.py' to set up OAuth."
            )
        flow = InstalledAppFlow.from_client_secrets_file(secrets_path, SCOPES)
        creds = flow.run_local_server(port=0)
        _save_credentials(creds, tokens_path)
        logger.info("OAuth credentials saved to %s", tokens_path)

    return creds


def _save_credentials(creds: Credentials, tokens_path: str) -> None:
    Path(tokens_path).parent.mkdir(parents=True, exist_ok=True)
    with open(tokens_path, "w") as f:
        f.write(creds.to_json())


def _build_client(channel_config: Dict):
    tokens_path = channel_config.get("youtube_tokens", "config/youtube_tokens.json")
    secrets_path = channel_config.get(
        "youtube_client_secrets", "config/youtube_client_secrets.json"
    )
    creds = _load_credentials(tokens_path, secrets_path)
    return build(YOUTUBE_API_SERVICE, YOUTUBE_API_VERSION, credentials=creds)


def upload_video(
    video_path: str,
    thumbnail_path: str,
    script: Dict,
    channel_config: Dict,
) -> Dict:
    """
    Uploads a video to YouTube and sets the thumbnail.
    Returns a dict with: video_id, url, title.
    """
    if not Path(video_path).exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    niche = channel_config.get("niche", "technology")
    video_cfg = channel_config.get("video", {})
    category_id = channel_config.get("category_id") or CATEGORY_MAP.get(niche, "28")

    title = script["title"][:100]
    description = _build_description(script, channel_config)
    tags = script.get("tags", [])[:500]  # YouTube tag limit
    privacy = video_cfg.get("privacy", "public")
    language = channel_config.get("language", "es")

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
            "defaultLanguage": language,
            "defaultAudioLanguage": language,
        },
        "status": {
            "privacyStatus": privacy,
            "madeForKids": video_cfg.get("made_for_kids", False),
            "selfDeclaredMadeForKids": video_cfg.get("made_for_kids", False),
        },
    }

    youtube = _build_client(channel_config)

    logger.info("Uploading video: '%s' (%s)…", title, privacy)
    video_id = _resumable_upload(youtube, video_path, body)

    url = f"https://www.youtube.com/watch?v={video_id}"
    logger.info("Upload complete: %s", url)

    if Path(thumbnail_path).exists():
        _set_thumbnail(youtube, video_id, thumbnail_path)

    return {"video_id": video_id, "url": url, "title": title}


@with_retry(max_attempts=4, base_delay=2.0, exceptions=(HttpError, Exception))
def _resumable_upload(youtube, video_path: str, body: Dict) -> str:
    """Performs a resumable upload and returns the video ID."""
    file_size_mb = Path(video_path).stat().st_size / (1024 * 1024)
    logger.info("Uploading %.1f MB via resumable upload…", file_size_mb)

    media = MediaFileUpload(
        video_path,
        mimetype="video/mp4",
        chunksize=10 * 1024 * 1024,  # 10 MB chunks
        resumable=True,
    )

    request = youtube.videos().insert(
        part=",".join(body.keys()),
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            logger.info("Upload progress: %d%%", pct)

    return response["id"]


@with_retry(max_attempts=3, base_delay=2.0, exceptions=(HttpError,))
def _set_thumbnail(youtube, video_id: str, thumbnail_path: str) -> None:
    """Sets a custom thumbnail. File must be < 2MB."""
    size_kb = Path(thumbnail_path).stat().st_size // 1024
    if size_kb > 2000:
        logger.warning("Thumbnail too large (%d KB). Skipping.", size_kb)
        return

    media = MediaFileUpload(thumbnail_path, mimetype="image/png")
    youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
    logger.info("Thumbnail set for video %s", video_id)


def _build_description(script: Dict, channel_config: Dict) -> str:
    """Builds the full YouTube description with chapters, tags context, and attribution."""
    description = script.get("description", "")

    # Append chapter timestamps if not already in description
    chapters = script.get("chapters", [])
    if chapters and "00:00" not in description:
        description += "\n\n── CAPÍTULOS ──\n" if channel_config.get("language") == "es" else "\n\n── CHAPTERS ──\n"
        for chapter in chapters:
            ts = chapter.get("timestamp", "00:00")
            title = chapter.get("title", "")
            description += f"{ts} - {title}\n"

    # AI disclosure (required by YouTube policy as of 2025)
    if channel_config.get("language") == "es":
        disclosure = "\n\n⚠️ Este vídeo ha sido producido con asistencia de inteligencia artificial."
    else:
        disclosure = "\n\n⚠️ This video was produced with AI assistance."

    description += disclosure

    # Pexels attribution (required by Pexels license)
    description += "\n\nStock footage provided by Pexels (pexels.com)"

    return description[:5000]  # YouTube description limit
