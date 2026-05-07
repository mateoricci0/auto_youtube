"""
Downloads stock video clips from Pexels API (free, commercial use allowed).
Pexels requires attribution in the video description (handled in the upload module).
"""
import os
import uuid
from pathlib import Path
from typing import List, Optional

import requests

from src.utils.logger import get_logger
from src.utils.retry import with_retry

logger = get_logger("pexels")

PEXELS_API = "https://api.pexels.com/videos/search"
HEADERS_TEMPLATE = {"Authorization": "{api_key}"}
PREFERRED_QUALITY = ["hd", "sd", "mobile"]  # quality preference order


@with_retry(max_attempts=3, base_delay=2.0, exceptions=(requests.RequestException,))
def _search_videos(keyword: str, api_key: str, per_page: int = 5) -> List[dict]:
    headers = {"Authorization": api_key}
    params = {
        "query": keyword,
        "per_page": per_page,
        "orientation": "landscape",
        "size": "medium",  # at least 1280x720
    }
    resp = requests.get(PEXELS_API, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("videos", [])


def _pick_video_url(video: dict) -> Optional[str]:
    """Pick the best available video file URL from a Pexels video object."""
    files = video.get("video_files", [])
    # Sort by quality preference then by width descending
    for quality in PREFERRED_QUALITY:
        candidates = [f for f in files if f.get("quality") == quality]
        if candidates:
            best = max(candidates, key=lambda f: f.get("width", 0))
            return best.get("link")
    # Fallback: any file
    if files:
        return files[0].get("link")
    return None


@with_retry(max_attempts=3, base_delay=2.0, exceptions=(requests.RequestException,))
def _download_file(url: str, dest_path: str) -> None:
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                f.write(chunk)


def fetch_clips(
    keywords: List[str],
    output_dir: str,
    clips_per_keyword: int = 2,
) -> List[str]:
    """
    Searches Pexels for each keyword and downloads video clips.
    Returns a list of local file paths. Falls back gracefully if API key missing.
    """
    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        logger.warning("PEXELS_API_KEY not set. Video will use solid color background.")
        return []

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    downloaded = []

    for keyword in keywords:
        logger.info("Searching Pexels for: '%s'", keyword)
        try:
            videos = _search_videos(keyword, api_key, per_page=clips_per_keyword + 2)
            count = 0
            for video in videos:
                if count >= clips_per_keyword:
                    break
                url = _pick_video_url(video)
                if not url:
                    continue
                dest = str(Path(output_dir) / f"clip_{uuid.uuid4().hex[:8]}.mp4")
                logger.info("Downloading clip from Pexels (%s)...", keyword)
                _download_file(url, dest)
                downloaded.append(dest)
                count += 1
        except Exception as exc:
            logger.warning("Failed to fetch Pexels clips for '%s': %s", keyword, exc)

    logger.info("Downloaded %d stock clips total", len(downloaded))
    return downloaded
