"""
Composes the final video from stock clips + TTS audio + text overlays.
Uses MoviePy 1.0.3 + Pillow for text overlays (no ImageMagick required).

Output: 1920x1080, 24fps, H.264, AAC audio.
Rendering typically takes 20-40 minutes on a standard CPU for an 8-minute video.
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

logger = get_logger("composer")

TARGET_W, TARGET_H = 1920, 1080
TARGET_FPS = 24
FONT_PATHS = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _make_text_overlay_array(
    text: str,
    width: int = TARGET_W,
    font_size: int = 52,
    bg_alpha: int = 180,
) -> np.ndarray:
    """Creates a semi-transparent text overlay as a numpy RGBA array."""
    bar_height = int(TARGET_H * 0.12)
    img = Image.new("RGBA", (width, bar_height), (0, 0, 0, bg_alpha))
    draw = ImageDraw.Draw(img)
    font = _find_font(font_size)

    # Measure text to center it
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = max(0, (width - tw) // 2)
    y = max(0, (bar_height - th) // 2)

    # Drop shadow
    draw.text((x + 2, y + 2), text, font=font, fill=(0, 0, 0, 200))
    # Main text
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    return np.array(img)


def _make_intro_frame_array(title: str, width: int = TARGET_W, height: int = TARGET_H) -> np.ndarray:
    """Creates a branded intro title card as a numpy RGB array."""
    img = Image.new("RGB", (width, height), (15, 15, 30))  # dark navy background
    draw = ImageDraw.Draw(img)

    # Accent line
    draw.rectangle([(width // 4, height // 2 - 60), (3 * width // 4, height // 2 - 56)], fill=(229, 69, 96))

    # Title text
    font_large = _find_font(72)
    words = title.split()
    # Wrap to two lines if needed
    mid = len(words) // 2
    line1 = " ".join(words[:mid]) if mid > 0 else title
    line2 = " ".join(words[mid:]) if mid > 0 else ""

    for i, line in enumerate([line1, line2]):
        if not line:
            continue
        bbox = draw.textbbox((0, 0), line, font=font_large)
        tw = bbox[2] - bbox[0]
        x = (width - tw) // 2
        y = height // 2 - 30 + i * 85
        draw.text((x + 3, y + 3), line, font=font_large, fill=(0, 0, 0, 180))
        draw.text((x, y), line, font=font_large, fill=(255, 255, 255))

    return np.array(img)


def _parse_timestamp(ts: str) -> float:
    """Convert 'MM:SS' or 'HH:MM:SS' string to seconds."""
    parts = ts.strip().split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        pass
    return 0.0


def compose_video(
    audio_path: str,
    clip_paths: List[str],
    script: Dict,
    output_dir: str,
) -> str:
    """
    Assembles the final video file. Returns output file path.
    Falls back to a solid color background if no clips are available.
    """
    # Import here to avoid slow startup on import
    from moviepy.editor import (
        AudioFileClip,
        ColorClip,
        CompositeVideoClip,
        ImageClip,
        VideoFileClip,
        concatenate_videoclips,
    )

    output_path = str(Path(output_dir) / f"video_{uuid.uuid4().hex[:8]}.mp4")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    audio = AudioFileClip(audio_path)
    total_duration = audio.duration
    logger.info("Composing video: audio duration=%.1fs", total_duration)

    # --- Build base video track ---
    if clip_paths:
        loaded_clips = []
        for path in clip_paths:
            try:
                clip = VideoFileClip(path).resize((TARGET_W, TARGET_H))
                loaded_clips.append(clip)
                logger.debug("Loaded clip: %s (%.1fs)", Path(path).name, clip.duration)
            except Exception as exc:
                logger.warning("Skipping unreadable clip %s: %s", path, exc)

        if loaded_clips:
            # Concatenate and loop until we cover the full audio duration
            concatenated = concatenate_videoclips(loaded_clips, method="compose")
            if concatenated.duration < total_duration:
                n = int(total_duration / concatenated.duration) + 1
                concatenated = concatenate_videoclips([concatenated] * n, method="compose")
            base = concatenated.subclip(0, total_duration).without_audio()
        else:
            base = ColorClip((TARGET_W, TARGET_H), color=(15, 15, 30), duration=total_duration)
    else:
        base = ColorClip((TARGET_W, TARGET_H), color=(15, 15, 30), duration=total_duration)

    # --- Build overlay layers ---
    layers = [base]

    # Intro title card (first 5 seconds)
    intro_duration = min(5.0, total_duration * 0.1)
    intro_array = _make_intro_frame_array(script.get("title", ""))
    intro_clip = (
        ImageClip(intro_array, duration=intro_duration)
        .set_start(0)
        .set_position("center")
    )
    layers.append(intro_clip)

    # Chapter section title overlays
    chapters = script.get("chapters", [])
    for chapter in chapters[1:]:  # Skip intro chapter
        title = chapter.get("title", "").strip()
        ts = _parse_timestamp(chapter.get("timestamp", "0:00"))
        if not title or ts >= total_duration - 4:
            continue

        overlay_duration = min(3.0, total_duration - ts - 1)
        overlay_array = _make_text_overlay_array(title)
        overlay_clip = (
            ImageClip(overlay_array, duration=overlay_duration)
            .set_start(ts)
            .set_position(("center", TARGET_H - overlay_array.shape[0] - 30))
        )
        layers.append(overlay_clip)

    # --- Final composite ---
    final = CompositeVideoClip(layers, size=(TARGET_W, TARGET_H)).set_audio(audio)

    logger.info("Rendering video to %s (this may take 20-40 minutes)...", output_path)
    final.write_videofile(
        output_path,
        fps=TARGET_FPS,
        codec="libx264",
        audio_codec="aac",
        bitrate="2000k",
        audio_bitrate="128k",
        threads=max(1, os.cpu_count() - 1),
        logger=None,
        preset="medium",
    )

    # Cleanup MoviePy clips to free memory
    audio.close()
    final.close()
    for clip in (loaded_clips if clip_paths else []):
        try:
            clip.close()
        except Exception:
            pass

    file_mb = Path(output_path).stat().st_size // (1024 * 1024)
    logger.info("Video rendered: %s (%d MB)", output_path, file_mb)
    return output_path
