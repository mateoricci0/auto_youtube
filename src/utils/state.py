"""
Simple JSON-based state store.
Tracks which topics have already been used per channel so we never repeat.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from src.utils.logger import get_logger

logger = get_logger("state")

_STATE_FILE = Path(os.getenv("OUTPUT_DIR", "output")) / "state.json"


def _load() -> Dict:
    if _STATE_FILE.exists():
        try:
            with open(_STATE_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.warning("Could not read state file: %s. Starting fresh.", exc)
    return {}


def _save(state: Dict) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_used_topics(channel_id: str) -> List[str]:
    return _load().get(channel_id, {}).get("used_topics", [])


def mark_topic_used(channel_id: str, topic: str) -> None:
    state = _load()
    channel_state = state.setdefault(channel_id, {"used_topics": [], "uploads": []})
    if topic not in channel_state["used_topics"]:
        channel_state["used_topics"].append(topic)
        # Keep only the last 100 topics to avoid unbounded growth
        channel_state["used_topics"] = channel_state["used_topics"][-100:]
    _save(state)


def record_upload(channel_id: str, video_id: str, title: str, url: str) -> None:
    state = _load()
    channel_state = state.setdefault(channel_id, {"used_topics": [], "uploads": []})
    channel_state["uploads"].append(
        {
            "video_id": video_id,
            "title": title,
            "url": url,
            "date": datetime.utcnow().isoformat(),
        }
    )
    state[channel_id]["last_run"] = datetime.utcnow().isoformat()
    _save(state)
