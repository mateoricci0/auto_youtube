"""
Script generator using DeepSeek V3 (production) and R1 (strategic topic selection).
DeepSeek uses the OpenAI-compatible API format.
"""
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from openai import OpenAI

from src.utils.logger import get_logger
from src.utils.retry import with_retry

logger = get_logger("script")


def _get_client() -> OpenAI:
    return OpenAI(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )


def _load_prompt(language: str) -> str:
    lang = language.lower()[:2]
    prompt_file = Path("prompts") / f"script_{lang}.txt"
    if not prompt_file.exists():
        prompt_file = Path("prompts") / "script_en.txt"
    return prompt_file.read_text(encoding="utf-8")


def _extract_json(text: str) -> str:
    """Extract JSON from a response that may have extra text or markdown fences."""
    # Try direct parse first
    text = text.strip()
    if text.startswith("{"):
        return text

    # Strip ```json ... ``` fences
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return match.group(1)

    # Look for a JSON object anywhere in the text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)

    raise ValueError("No JSON object found in model response.")


@with_retry(max_attempts=3, base_delay=3.0)
def select_best_topic(topics: List[str], channel_config: Dict) -> str:
    """
    Uses DeepSeek R1 to pick the best topic from the trending list.
    Called once per pipeline run — slightly more expensive but worth it.
    """
    client = _get_client()
    model = os.getenv("DEEPSEEK_R1_MODEL", "deepseek-reasoner")

    niche = channel_config.get("niche", "technology")
    language = channel_config.get("language", "es")
    keywords = ", ".join(channel_config.get("niche_keywords", []))

    topics_text = "\n".join(f"{i+1}. {t}" for i, t in enumerate(topics[:10]))

    system_prompt = (
        "You are a YouTube channel strategist. Your job is to select the single best "
        "topic from a list of trending videos to maximize views and engagement."
    )

    if language == "es":
        user_prompt = (
            f"Nicho del canal: {niche}\n"
            f"Palabras clave objetivo: {keywords}\n\n"
            f"Temas trending:\n{topics_text}\n\n"
            "Selecciona el tema con mayor potencial de views para este nicho. "
            "Responde SOLO con el texto exacto del tema elegido, sin explicación."
        )
    else:
        user_prompt = (
            f"Channel niche: {niche}\n"
            f"Target keywords: {keywords}\n\n"
            f"Trending topics:\n{topics_text}\n\n"
            "Select the single topic with the highest view potential for this niche. "
            "Respond ONLY with the exact topic text, no explanation."
        )

    logger.info("Selecting best topic using %s...", model)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=500,
    )

    selected = response.choices[0].message.content.strip()
    logger.info("Selected topic: %s", selected[:100])
    return selected


@with_retry(max_attempts=3, base_delay=3.0)
def generate_script(topic: str, channel_config: Dict) -> Dict:
    """
    Generates a full video script with metadata using DeepSeek V3.
    Returns a dict with: title, description, tags, thumbnail_text,
    pexels_keywords, chapters (list of {timestamp, title, narration}).
    """
    client = _get_client()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    language = channel_config.get("language", "es")
    niche = channel_config.get("niche", "technology")
    niche_keywords = ", ".join(channel_config.get("niche_keywords", []))
    target_minutes = channel_config.get("video", {}).get("target_duration_minutes", 8)

    prompt_template = _load_prompt(language)
    prompt = prompt_template.format(
        topic=topic,
        niche=niche,
        niche_keywords=niche_keywords,
        target_duration_minutes=target_minutes,
    )

    logger.info("Generating script with %s for topic: %s", model, topic[:80])
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a professional YouTube scriptwriter. "
                    "Always respond with valid JSON only, no extra text."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=4000,
        temperature=0.7,
    )

    raw = response.choices[0].message.content
    logger.debug("Raw model response length: %d chars", len(raw))

    try:
        json_str = _extract_json(raw)
        script = json.loads(json_str)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error("Failed to parse script JSON: %s\nRaw response: %s", exc, raw[:500])
        raise RuntimeError(f"Script JSON parsing failed: {exc}") from exc

    _validate_script(script)
    logger.info("Script generated: '%s' (%d chapters)", script["title"], len(script["chapters"]))
    return script


def _validate_script(script: Dict) -> None:
    required = ["title", "description", "tags", "thumbnail_text", "pexels_keywords", "chapters"]
    for field in required:
        if field not in script:
            raise ValueError(f"Script missing required field: {field}")

    if not script["chapters"]:
        raise ValueError("Script has no chapters.")

    for chapter in script["chapters"]:
        for field in ["timestamp", "title", "narration"]:
            if field not in chapter:
                raise ValueError(f"Chapter missing field: {field}")


def get_full_narration(script: Dict) -> str:
    """Concatenates all chapter narrations into a single text string for TTS."""
    parts = []
    for chapter in script["chapters"]:
        narration = chapter.get("narration", "").strip()
        if narration:
            parts.append(narration)
    return "\n\n".join(parts)
