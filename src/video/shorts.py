"""
Generates a viral-style vertical YouTube Short (1080x1920, max 57s).
Features:
  - Burn-in captions synchronized to TTS word timings (like viral Shorts)
  - Ken Burns zoom effect on stock footage
  - Title banner + subscribe CTA
"""
import os
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# MoviePy 1.0.3 references PIL.Image.ANTIALIAS which was removed in Pillow 10+
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

from src.utils.logger import get_logger

logger = get_logger("shorts")

SHORT_W, SHORT_H = 1080, 1920
SHORT_MAX_DURATION = 57
SHORT_FPS = 30
WORDS_PER_CAPTION = 4  # words shown per caption phrase

FONT_PATHS = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ── Caption helpers ────────────────────────────────────────────────────────────

def _group_words_into_phrases(timings: list, words_per_phrase: int = WORDS_PER_CAPTION) -> list:
    """Groups word timings into timed caption phrases."""
    phrases = []
    for i in range(0, len(timings), words_per_phrase):
        group = timings[i:i + words_per_phrase]
        start = group[0]["start"]
        end = group[-1]["start"] + group[-1]["duration"]
        text = " ".join(w["word"] for w in group)
        phrases.append({"text": text, "start": start, "duration": max(end - start, 0.3)})
    return phrases


def _make_caption_image(text: str) -> np.ndarray:
    """Renders a caption phrase as RGBA numpy array (full Short width)."""
    font = _find_font(82)
    max_w = SHORT_W - 80
    padding = 18

    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    # Word-wrap
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        bbox = dummy.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_w:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    line_h = 95
    box_h = len(lines) * line_h + padding * 2
    img = Image.new("RGBA", (SHORT_W, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    y = padding
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        lx = (SHORT_W - lw) // 2

        # Dark pill background
        draw.rounded_rectangle(
            [lx - 14, y - 6, lx + lw + 14, y + line_h - 10],
            radius=12,
            fill=(0, 0, 0, 175),
        )
        # Outline
        for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
            draw.text((lx + dx, y + dy), line, font=font, fill=(0, 0, 0, 255))
        # White text
        draw.text((lx, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h

    return np.array(img)


def _build_caption_clips(phrases: list, total_duration: float):
    """Returns a list of MoviePy ImageClips for each caption phrase."""
    from moviepy.editor import ImageClip

    clips = []
    caption_y = int(SHORT_H * 0.60)  # 60% down — center-bottom, avoids UI chrome

    for phrase in phrases:
        start = phrase["start"]
        dur = phrase["duration"]
        if start >= total_duration:
            break
        dur = min(dur, total_duration - start)

        arr = _make_caption_image(phrase["text"])
        clip = (
            ImageClip(arr, duration=dur)
            .set_start(start)
            .set_position(("center", caption_y))
        )
        clips.append(clip)

    return clips


# ── Ken Burns effect ───────────────────────────────────────────────────────────

def _apply_kenburns(clip, zoom_start: float = 1.0, zoom_end: float = 1.08):
    """Slow zoom-in effect to make static footage feel dynamic."""
    dur = max(clip.duration, 0.1)
    return clip.resize(lambda t: zoom_start + (zoom_end - zoom_start) * (t / dur))


# ── Banner helpers ─────────────────────────────────────────────────────────────

def _make_title_banner(title: str) -> np.ndarray:
    banner_h = 155
    img = Image.new("RGBA", (SHORT_W, banner_h), (229, 69, 96, 230))
    draw = ImageDraw.Draw(img)
    font = _find_font(46)

    words = title.split()
    lines, current = [], ""
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for word in words:
        test = (current + " " + word).strip()
        bbox = dummy.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= SHORT_W - 40:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    line_h = 54
    y = (banner_h - len(lines) * line_h) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (SHORT_W - (bbox[2] - bbox[0])) // 2
        draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 180))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_h

    return np.array(img)


def _make_subscribe_banner() -> np.ndarray:
    banner_h = 100
    img = Image.new("RGBA", (SHORT_W, banner_h), (15, 15, 30, 220))
    draw = ImageDraw.Draw(img)
    font = _find_font(40)
    text = "Suscríbete a TechHoy"
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (SHORT_W - (bbox[2] - bbox[0])) // 2
    y = (banner_h - (bbox[3] - bbox[1])) // 2
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    return np.array(img)


# ── Main entry point ───────────────────────────────────────────────────────────

def generate_short(
    shorts_hook_text: str,
    clip_paths: List[str],
    script: Dict,
    output_dir: str,
    language: str = "es",
) -> Optional[str]:
    """
    Generates a viral-style Short with captions and Ken Burns.
    Returns output file path, or None on failure.
    """
    try:
        from moviepy.editor import (
            AudioFileClip,
            ColorClip,
            CompositeVideoClip,
            ImageClip,
            VideoFileClip,
            concatenate_videoclips,
        )
        from src.tts.engine import synthesize_with_timing

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        output_path = str(Path(output_dir) / f"short_{uuid.uuid4().hex[:8]}.mp4")

        # Generate audio + word timings for captions
        logger.info("Synthesizing Short audio with word timings (%d chars)…", len(shorts_hook_text))
        audio_path, word_timings = synthesize_with_timing(shorts_hook_text, language, output_dir)
        audio = AudioFileClip(audio_path)

        duration = min(audio.duration, SHORT_MAX_DURATION)
        audio = audio.subclip(0, duration)

        logger.info("Short duration: %.1fs, word timings: %d", duration, len(word_timings))

        # ── Background: Ken Burns stock clips ─────────────────────────────
        base = _build_background(clip_paths, duration)

        # ── Overlays ───────────────────────────────────────────────────────
        layers = [base]

        # Title banner (top, always visible)
        title_arr = _make_title_banner(script.get("title", "TechHoy"))
        title_clip = ImageClip(title_arr, duration=duration).set_position(("center", 0))
        layers.append(title_clip)

        # Burn-in captions (if we have timing data)
        if word_timings:
            phrases = _group_words_into_phrases(word_timings)
            caption_clips = _build_caption_clips(phrases, duration)
            layers.extend(caption_clips)
            logger.info("Added %d caption phrases", len(caption_clips))
        else:
            logger.warning("No word timings — captions skipped")

        # Subscribe CTA (last 3.5 seconds)
        sub_arr = _make_subscribe_banner()
        cta_start = max(0, duration - 3.5)
        sub_clip = (
            ImageClip(sub_arr, duration=min(3.5, duration))
            .set_start(cta_start)
            .set_position(("center", SHORT_H - sub_arr.shape[0]))
        )
        layers.append(sub_clip)

        # ── Render ─────────────────────────────────────────────────────────
        final = CompositeVideoClip(layers, size=(SHORT_W, SHORT_H)).set_audio(audio)

        logger.info("Rendering Short to %s…", output_path)
        final.write_videofile(
            output_path,
            fps=SHORT_FPS,
            codec="libx264",
            audio_codec="aac",
            bitrate="1500k",
            audio_bitrate="128k",
            threads=max(1, os.cpu_count() - 1),
            logger=None,
        )

        audio.close()
        final.close()

        logger.info("Short rendered: %s", output_path)
        return output_path

    except Exception as exc:
        logger.error("Short generation failed: %s", exc)
        return None


def _build_background(clip_paths: List[str], duration: float):
    """Loads stock clips, applies Ken Burns, concatenates to fill duration."""
    from moviepy.editor import ColorClip, VideoFileClip, concatenate_videoclips

    if not clip_paths:
        return ColorClip((SHORT_W, SHORT_H), color=(15, 15, 30), duration=duration)

    loaded = []
    directions = ["in", "out"]  # alternate zoom direction per clip
    for i, path in enumerate(clip_paths[:4]):
        try:
            clip = VideoFileClip(path)
            # Crop to portrait
            w, h = clip.size
            crop_w = int(h * SHORT_W / SHORT_H)
            if crop_w <= w:
                x1 = (w - crop_w) // 2
                clip = clip.crop(x1=x1, y1=0, x2=x1 + crop_w, y2=h)
            clip = clip.resize((SHORT_W, SHORT_H))
            # Ken Burns
            zoom_end = 1.10 if directions[i % 2] == "in" else 1.0
            zoom_start = 1.0 if directions[i % 2] == "in" else 1.10
            clip = _apply_kenburns(clip, zoom_start=zoom_start, zoom_end=zoom_end)
            loaded.append(clip)
        except Exception as exc:
            logger.warning("Skipping clip for Short: %s", exc)

    if not loaded:
        return ColorClip((SHORT_W, SHORT_H), color=(15, 15, 30), duration=duration)

    base = concatenate_videoclips(loaded, method="compose")
    if base.duration < duration:
        n = int(duration / base.duration) + 1
        base = concatenate_videoclips([base] * n, method="compose")
    return base.subclip(0, duration).without_audio()
