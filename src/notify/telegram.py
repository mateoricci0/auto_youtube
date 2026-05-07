"""
Telegram notifications via Bot API (no library needed — pure HTTP).
Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.
If not configured, notifications are silently skipped.
"""
import os

import requests

from src.utils.logger import get_logger

logger = get_logger("telegram")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _is_configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def send(message: str) -> None:
    """Send a plain text message. Silently skips if not configured."""
    if not _is_configured():
        return

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = TELEGRAM_API.format(token=token)

    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as exc:
        # Notification failure should never crash the pipeline
        logger.warning("Telegram notification failed: %s", exc)


def notify_success(channel_name: str, title: str, url: str) -> None:
    send(
        f"✅ <b>Vídeo publicado</b>\n"
        f"Canal: {channel_name}\n"
        f"Título: <i>{title}</i>\n"
        f"URL: {url}"
    )


def notify_error(channel_name: str, step: str, error: str) -> None:
    send(
        f"❌ <b>Error en pipeline</b>\n"
        f"Canal: {channel_name}\n"
        f"Paso: {step}\n"
        f"Error: <code>{error[:300]}</code>"
    )


def notify_start(channel_name: str, topic: str) -> None:
    send(
        f"🚀 <b>Pipeline iniciado</b>\n"
        f"Canal: {channel_name}\n"
        f"Tema: {topic[:100]}"
    )
