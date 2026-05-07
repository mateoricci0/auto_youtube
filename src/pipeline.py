"""
Main pipeline orchestrator.
Runs the complete flow for a single channel:
  trends → topic selection → script → TTS → stock footage → video + Short → thumbnail → upload
"""
import os
import shutil
import traceback
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
from src.utils.state import mark_topic_used, record_upload
from src.video.composer import compose_video
from src.video.pexels import fetch_clips
from src.video.shorts import generate_short

logger = get_logger("pipeline")


def run_pipeline(channel_config: Dict) -> Dict:
    """
    Executes the full video production pipeline for a channel.
    Returns a result dict with status, video_id, url, and title (or error).
    """
    channel_id = channel_config["id"]
    channel_name = channel_config.get("name", channel_id)
    language = channel_config.get("language", "es")
    output_dir = os.getenv("OUTPUT_DIR", "output")
    generate_shorts = channel_config.get("video", {}).get("generate_shorts", False)

    run_id = uuid.uuid4().hex[:10]
    work_dir = Path(output_dir) / f"run_{run_id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("Starting pipeline for channel: %s (run_id=%s)", channel_name, run_id)

    try:
        # ── STEP 1: Fetch trending topics ──────────────────────────────
        logger.info("[1/8] Fetching trending topics…")
        topics = fetch_trending_topics(channel_config)
        if not topics:
            raise RuntimeError("No trending topics found — check YOUTUBE_API_KEY and quota.")

        # ── STEP 2: Select best topic ───────────────────────────────────
        logger.info("[2/8] Selecting best topic from %d candidates…", len(topics))
        topic = select_best_topic(topics, channel_config)
        telegram.notify_start(channel_name, topic)
        mark_topic_used(channel_id, topic.split("|")[0].strip())

        # ── STEP 3: Generate script ─────────────────────────────────────
        logger.info("[3/8] Generating script…")
        script = generate_script(topic, channel_config)

        # ── STEP 4: Text-to-Speech ──────────────────────────────────────
        logger.info("[4/8] Synthesizing main audio…")
        narration_text = get_full_narration(script)
        audio_path = synthesize(narration_text, language, str(work_dir))

        # ── STEP 5: Fetch stock footage ─────────────────────────────────
        logger.info("[5/8] Fetching stock footage from Pexels…")
        pexels_keywords = script.get("pexels_keywords", ["technology", "computer", "digital"])
        clip_paths = fetch_clips(pexels_keywords, str(work_dir), clips_per_keyword=2)

        # ── STEP 6: Compose main video ──────────────────────────────────
        logger.info("[6/8] Composing video (may take 20-40 min on CPU)…")
        video_path = compose_video(audio_path, clip_paths, script, str(work_dir))

        # ── STEP 7: Generate thumbnail ──────────────────────────────────
        logger.info("[7/8] Generating thumbnail…")
        thumbnail_path = generate_thumbnail(
            script.get("thumbnail_text", script["title"]),
            str(work_dir),
            video_path=video_path,
        )

        # ── STEP 8: Upload main video to YouTube ────────────────────────
        logger.info("[8/8] Uploading to YouTube…")
        result = upload_video(video_path, thumbnail_path, script, channel_config)
        record_upload(channel_id, result["video_id"], result["title"], result["url"])

        # ── STEP 9 (optional): Generate and upload Short ────────────────
        short_result = None
        if generate_shorts:
            logger.info("[+] Generating YouTube Short…")
            shorts_hook = script.get("shorts_hook", "")
            if shorts_hook:
                short_path = generate_short(
                    shorts_hook, clip_paths, script, str(work_dir), language
                )
                if short_path:
                    short_script = _build_short_script(script, language)
                    short_config = {**channel_config, "video": {**channel_config.get("video", {}), "generate_shorts": False}}
                    short_result = upload_video(short_path, thumbnail_path, short_script, short_config)
                    logger.info("Short uploaded: %s", short_result.get("url"))

        # ── Notify ──────────────────────────────────────────────────────
        msg = f"🎬 <b>{result['title']}</b>\n{result['url']}"
        if short_result:
            msg += f"\n▶️ Short: {short_result['url']}"
        telegram.notify_success(channel_name, result["title"], result["url"])
        if short_result:
            telegram.send(f"📱 Short publicado: {short_result['url']}")

        logger.info("Pipeline complete! %s", result["url"])
        return {"status": "success", **result, "short": short_result}

    except Exception as exc:
        step = _identify_failed_step()
        logger.exception("Pipeline failed at step '%s': %s", step, exc)
        telegram.notify_error(channel_name, step, str(exc))
        return {"status": "error", "error": str(exc), "step": step}

    finally:
        _cleanup(work_dir)


def _build_short_script(script: Dict, language: str) -> Dict:
    """Builds a minimal script dict for the Short upload."""
    title = script["title"]
    short_title = f"#Shorts {title[:90]}" if len(title) < 90 else f"#Shorts {title[:87]}…"
    if language == "es":
        description = f"#Shorts\n\n{script.get('description', '')[:300]}\n\nSuscríbete a TechHoy para más tech en español."
    else:
        description = f"#Shorts\n\n{script.get('description', '')[:300]}\n\nSubscribe for more tech content."
    return {
        "title": short_title,
        "description": description,
        "tags": script.get("tags", []) + ["Shorts", "TechHoy"],
        "thumbnail_text": script.get("thumbnail_text", ""),
        "pexels_keywords": script.get("pexels_keywords", []),
        "chapters": [],
    }


def _identify_failed_step() -> str:
    tb = traceback.format_exc()
    checks = {
        "fetch_trends": ["trends", "fetcher"],
        "generate_script": ["script", "generator", "deepseek"],
        "text_to_speech": ["tts", "synthesize", "engine"],
        "fetch_stock_footage": ["pexels"],
        "compose_video": ["composer", "moviepy"],
        "generate_thumbnail": ["thumbnail"],
        "upload_youtube": ["upload", "youtube"],
        "generate_short": ["shorts"],
    }
    tb_lower = tb.lower()
    for step, keywords in checks.items():
        if any(k in tb_lower for k in keywords):
            return step
    return "unknown"


def _cleanup(work_dir: Path) -> None:
    try:
        if work_dir.exists():
            shutil.rmtree(work_dir)
            logger.info("Cleaned up temp directory: %s", work_dir)
    except Exception as exc:
        logger.warning("Cleanup failed: %s", exc)
