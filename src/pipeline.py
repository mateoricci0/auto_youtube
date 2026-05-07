"""
Main pipeline orchestrator.
Runs the complete flow for a single channel:
  trends → topic selection → script → TTS → stock footage → video → thumbnail → upload
"""
import os
import shutil
import uuid
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv

load_dotenv()

from src.notify import telegram
from src.script.generator import generate_script, get_full_narration, select_best_topic
from src.thumbnail.generator import generate_thumbnail
from src.trends.fetcher import fetch_trending_topics
from src.tts.engine import synthesize
from src.upload.youtube import upload_video
from src.utils.logger import get_logger
from src.utils.state import get_used_topics, mark_topic_used, record_upload
from src.video.composer import compose_video
from src.video.pexels import fetch_clips

logger = get_logger("pipeline")


def run_pipeline(channel_config: Dict) -> Dict:
    """
    Executes the full video production pipeline for a channel.
    Returns a result dict with status, video_id, url, and title (or error).
    """
    channel_id = channel_config["id"]
    channel_name = channel_config.get("name", channel_id)
    output_dir = os.getenv("OUTPUT_DIR", "output")

    # Create a unique working directory for this run's temp files
    run_id = uuid.uuid4().hex[:10]
    work_dir = Path(output_dir) / f"run_{run_id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("Starting pipeline for channel: %s (run_id=%s)", channel_name, run_id)

    audio_path = None
    clip_paths = []
    video_path = None
    thumbnail_path = None

    try:
        # ── STEP 1: Fetch trending topics ──────────────────────────────
        logger.info("[1/8] Fetching trending topics…")
        topics = fetch_trending_topics(channel_config)

        if not topics:
            raise RuntimeError("No trending topics found — check YouTube API key and quota.")

        # ── STEP 2: Select best topic ───────────────────────────────────
        logger.info("[2/8] Selecting best topic from %d candidates…", len(topics))
        topic = select_best_topic(topics, channel_config)

        telegram.notify_start(channel_name, topic)
        mark_topic_used(channel_id, topic.split("|")[0].strip())

        # ── STEP 3: Generate script ─────────────────────────────────────
        logger.info("[3/8] Generating script…")
        script = generate_script(topic, channel_config)

        # ── STEP 4: Text-to-Speech ──────────────────────────────────────
        logger.info("[4/8] Synthesizing audio…")
        narration_text = get_full_narration(script)
        audio_path = synthesize(narration_text, channel_config.get("language", "es"), str(work_dir))

        # ── STEP 5: Fetch stock footage ─────────────────────────────────
        logger.info("[5/8] Fetching stock footage from Pexels…")
        pexels_keywords = script.get("pexels_keywords", ["technology", "computer", "digital"])
        clip_paths = fetch_clips(pexels_keywords, str(work_dir), clips_per_keyword=2)

        # ── STEP 6: Compose video ───────────────────────────────────────
        logger.info("[6/8] Composing video (this takes 20-40 min on CPU)…")
        video_path = compose_video(audio_path, clip_paths, script, str(work_dir))

        # ── STEP 7: Generate thumbnail ──────────────────────────────────
        logger.info("[7/8] Generating thumbnail…")
        thumbnail_path = generate_thumbnail(
            script.get("thumbnail_text", script["title"]),
            str(work_dir),
            video_path=video_path,
        )

        # ── STEP 8: Upload to YouTube ───────────────────────────────────
        logger.info("[8/8] Uploading to YouTube…")
        result = upload_video(video_path, thumbnail_path, script, channel_config)

        record_upload(channel_id, result["video_id"], result["title"], result["url"])
        telegram.notify_success(channel_name, result["title"], result["url"])

        logger.info("Pipeline complete! Video URL: %s", result["url"])
        return {"status": "success", **result}

    except Exception as exc:
        step = _identify_failed_step(exc)
        logger.exception("Pipeline failed at step '%s': %s", step, exc)
        telegram.notify_error(channel_name, step, str(exc))
        return {"status": "error", "error": str(exc), "step": step}

    finally:
        _cleanup(work_dir, audio_path, clip_paths, video_path, thumbnail_path)


def _identify_failed_step(exc: Exception) -> str:
    """Guess which pipeline step caused the error from the traceback module names."""
    tb_str = ""
    import traceback
    tb_str = "".join(traceback.format_exc())
    if "trends" in tb_str:
        return "fetch_trends"
    if "script" in tb_str or "deepseek" in tb_str.lower() or "generator" in tb_str:
        return "generate_script"
    if "tts" in tb_str or "synthesize" in tb_str:
        return "text_to_speech"
    if "pexels" in tb_str:
        return "fetch_stock_footage"
    if "composer" in tb_str:
        return "compose_video"
    if "thumbnail" in tb_str:
        return "generate_thumbnail"
    if "upload" in tb_str:
        return "upload_youtube"
    return "unknown"


def _cleanup(work_dir: Path, audio_path, clip_paths, video_path, thumbnail_path) -> None:
    """Removes all temporary files after pipeline completion."""
    try:
        if work_dir.exists():
            shutil.rmtree(work_dir)
            logger.info("Cleaned up temp directory: %s", work_dir)
    except Exception as exc:
        logger.warning("Cleanup failed: %s", exc)
