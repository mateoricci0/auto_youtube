"""
Generates a 1280x720 YouTube thumbnail using Pillow.
Design: blurred background from first video frame + gradient overlay + bold text.
Falls back to a solid color design if no video frame is available.
"""
import uuid
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from src.utils.logger import get_logger

logger = get_logger("thumbnail")

THUMB_W, THUMB_H = 1280, 720
FONT_PATHS = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
]
ACCENT_COLOR = (229, 69, 96)   # Red accent
TEXT_COLOR = (255, 255, 255)
DARK_BG = (10, 10, 20)


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _extract_first_frame(video_path: str) -> Optional[Image.Image]:
    """Extract the first frame from a video file as a PIL Image."""
    try:
        from moviepy.editor import VideoFileClip
        with VideoFileClip(video_path) as clip:
            frame = clip.get_frame(0)  # numpy array HxWx3
        return Image.fromarray(frame.astype("uint8"), "RGB")
    except Exception as exc:
        logger.warning("Could not extract frame from video: %s", exc)
        return None


def _build_background(frame: Optional[Image.Image]) -> Image.Image:
    """Creates the background layer: blurred frame or solid gradient."""
    if frame is not None:
        bg = frame.resize((THUMB_W, THUMB_H)).filter(ImageFilter.GaussianBlur(radius=12))
        # Darken to improve text contrast
        overlay = Image.new("RGB", (THUMB_W, THUMB_H), DARK_BG)
        bg = Image.blend(bg, overlay, alpha=0.55)
    else:
        # Gradient background as fallback
        bg = Image.new("RGB", (THUMB_W, THUMB_H))
        draw = ImageDraw.Draw(bg)
        for y in range(THUMB_H):
            r = int(DARK_BG[0] + (50 - DARK_BG[0]) * y / THUMB_H)
            g = int(DARK_BG[1] + (10 - DARK_BG[1]) * y / THUMB_H)
            b = int(DARK_BG[2] + (60 - DARK_BG[2]) * y / THUMB_H)
            draw.line([(0, y), (THUMB_W, y)], fill=(r, g, b))

    return bg


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list:
    """Wraps text to fit within max_width, returns list of lines."""
    words = text.split()
    lines = []
    current = ""
    dummy_img = Image.new("RGB", (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)

    for word in words:
        test = f"{current} {word}".strip()
        bbox = dummy_draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


def generate_thumbnail(
    thumbnail_text: str,
    output_dir: str,
    video_path: Optional[str] = None,
) -> str:
    """
    Creates a thumbnail for the video. Returns path to saved PNG file.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_path = str(Path(output_dir) / f"thumb_{uuid.uuid4().hex[:8]}.png")

    logger.info("Generating thumbnail: '%s'", thumbnail_text[:60])

    # Background
    frame = _extract_first_frame(video_path) if video_path else None
    bg = _build_background(frame)
    draw = ImageDraw.Draw(bg)

    # Accent bar on the left
    draw.rectangle([(60, 120), (72, THUMB_H - 120)], fill=ACCENT_COLOR)

    # Main text
    font_large = _find_font(96)
    padding = 100
    max_text_width = THUMB_W - padding * 2

    lines = _wrap_text(thumbnail_text.upper(), font_large, max_text_width)

    # Measure total text block height
    line_height = 110
    total_text_h = len(lines) * line_height
    start_y = (THUMB_H - total_text_h) // 2

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font_large)
        tw = bbox[2] - bbox[0]
        x = (THUMB_W - tw) // 2
        y = start_y + i * line_height

        # Shadow
        draw.text((x + 4, y + 4), line, font=font_large, fill=(0, 0, 0, 200))
        # Colored highlight on first line
        color = ACCENT_COLOR if i == 0 else TEXT_COLOR
        draw.text((x, y), line, font=font_large, fill=color)

    # Bottom accent line
    draw.rectangle([(0, THUMB_H - 8), (THUMB_W, THUMB_H)], fill=ACCENT_COLOR)

    bg.save(output_path, "PNG", optimize=True)
    size_kb = Path(output_path).stat().st_size // 1024
    logger.info("Thumbnail saved: %s (%d KB)", output_path, size_kb)
    return output_path
