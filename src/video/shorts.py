"""
Generates a vertical YouTube Short (1080x1920, max 58 seconds) from the
shorts_hook text in the script. Uses the same stock clips as the main video,
cropped to portrait orientation.
"""
import os
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from src.utils.logger import get_logger

logger = get_logger("shorts")

SHORT_W, SHORT_H = 1080, 1920
SHORT_MAX_DURATION = 57  # seconds — stay safely under the 60s limit
SHORT_FPS = 30
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


def _make_shorts_overlay(title: str) -> np.ndarray:
    """Top banner with the video title for the Short."""
    banner_h = 160
    img = Image.new("RGBA", (SHORT_W, banner_h), (229, 69, 96, 230))
    draw = ImageDraw.Draw(img)
    font = _find_font(44)

    # Wrap title to fit width
    words = title.split()
    lines, current = [], ""
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for word in words:
        test = f"{current} {word}".strip()
        bbox = dummy.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= SHORT_W - 40:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    y = (banner_h - len(lines) * 52) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        x = (SHORT_W - (bbox[2] - bbox[0])) // 2
        draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 180))
        draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += 52

    return np.array(img)


def _make_subscribe_banner() -> np.ndarray:
    """Bottom 'Suscríbete a TechHoy' call-to-action banner."""
    banner_h = 100
    img = Image.new("RGBA", (SHORT_W, banner_h), (15, 15, 30, 220))
    draw = ImageDraw.Draw(img)
    font = _find_font(40)
    text = "🔔 Suscríbete a TechHoy"
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (SHORT_W - (bbox[2] - bbox[0])) // 2
    y = (banner_h - (bbox[3] - bbox[1])) // 2
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    return np.array(img)


def generate_short(
    shorts_hook_text: str,
    clip_paths: List[str],
    script: Dict,
    output_dir: str,
    language: str = "es",
) -> Optional[str]:
    """
    Generates a vertical Short video from the hook text.
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
        from src.tts.engine import synthesize

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        output_path = str(Path(output_dir) / f"short_{uuid.uuid4().hex[:8]}.mp4")

        # Generate audio for the Short hook
        logger.info("Synthesizing Short audio (%d chars)…", len(shorts_hook_text))
        audio_path = synthesize(shorts_hook_text, language, output_dir)
        audio = AudioFileClip(audio_path)

        # Clamp to max Short duration
        duration = min(audio.duration, SHORT_MAX_DURATION)
        audio = audio.subclip(0, duration)

        # Build vertical base: crop center of landscape clip
        if clip_paths:
            loaded = []
            for path in clip_paths[:3]:
                try:
                    clip = VideoFileClip(path)
                    # Crop landscape to portrait: take center square then resize
                    w, h = clip.size
                    crop_w = int(h * SHORT_W / SHORT_H)
                    if crop_w <= w:
                        x1 = (w - crop_w) // 2
                        clip = clip.crop(x1=x1, y1=0, x2=x1 + crop_w, y2=h)
                    clip = clip.resize((SHORT_W, SHORT_H))
                    loaded.append(clip)
                except Exception as exc:
                    logger.warning("Skipping clip for Short: %s", exc)

            if loaded:
                base = concatenate_videoclips(loaded, method="compose")
                if base.duration < duration:
                    n = int(duration / base.duration) + 1
                    base = concatenate_videoclips([base] * n, method="compose")
                base = base.subclip(0, duration).without_audio()
            else:
                base = ColorClip((SHORT_W, SHORT_H), color=(15, 15, 30), duration=duration)
        else:
            base = ColorClip((SHORT_W, SHORT_H), color=(15, 15, 30), duration=duration)

        # Overlays
        layers = [base]

        # Title banner at top
        title_array = _make_shorts_overlay(script.get("title", "TechHoy"))
        title_clip = ImageClip(title_array, duration=duration).set_position(("center", 0))
        layers.append(title_clip)

        # Subscribe banner at bottom
        sub_array = _make_subscribe_banner()
        sub_clip = (
            ImageClip(sub_array, duration=3.0)
            .set_start(duration - 3.5)
            .set_position(("center", SHORT_H - sub_array.shape[0]))
        )
        layers.append(sub_clip)

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
