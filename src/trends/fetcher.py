"""
Fetches trending topics from YouTube Data API v3.
Costs ~1 unit per videos.list call — well within the 10,000/day free quota.
"""
import os
from typing import Dict, List

from googleapiclient.discovery import build

from src.utils.logger import get_logger
from src.utils.retry import with_retry
from src.utils.state import get_used_topics

logger = get_logger("trends")

# YouTube category IDs — maps niche names to category IDs
NICHE_CATEGORY_MAP = {
    "technology": "28",
    "science": "28",
    "education": "27",
    "news": "25",
    "finance": "22",
    "business": "22",
    "health": "26",
    "howto": "26",
    "entertainment": "24",
    "gaming": "20",
}


@with_retry(max_attempts=3, base_delay=2.0)
def fetch_trending_topics(channel_config: Dict, max_results: int = 20) -> List[str]:
    """
    Returns a list of trending topic strings for the channel's region/niche,
    excluding topics already used by this channel.
    """
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY not set in environment.")

    youtube = build("youtube", "v3", developerKey=api_key)

    region = channel_config.get("region", "US")
    niche = channel_config.get("niche", "technology")
    category_id = channel_config.get(
        "category_id", NICHE_CATEGORY_MAP.get(niche, "28")
    )

    logger.info("Fetching trending videos for region=%s, category=%s", region, category_id)

    response = (
        youtube.videos()
        .list(
            part="snippet",
            chart="mostPopular",
            regionCode=region,
            videoCategoryId=category_id,
            maxResults=max_results,
            hl=channel_config.get("language", "en"),
        )
        .execute()
    )

    used_topics = set(get_used_topics(channel_config["id"]))
    topics = []

    for item in response.get("items", []):
        snippet = item.get("snippet", {})
        title = snippet.get("title", "").strip()
        description = snippet.get("description", "").strip()
        tags = snippet.get("tags", [])

        if not title:
            continue

        # Build a rich topic string that gives context to the script generator
        topic_parts = [title]
        if tags:
            topic_parts.append("Keywords: " + ", ".join(tags[:5]))
        if description:
            # First 150 chars of description for extra context
            topic_parts.append(description[:150].replace("\n", " "))

        topic = " | ".join(topic_parts)

        if title not in used_topics:
            topics.append(topic)

    logger.info("Found %d fresh trending topics (excluded %d already used)", len(topics), len(used_topics))
    return topics
