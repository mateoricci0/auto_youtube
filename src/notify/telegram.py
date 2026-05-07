"""
Email notifications via Gmail SMTP.
Uses a Gmail App Password — no Telegram, no third-party service needed.

Setup (one time):
  1. Ve a myaccount.google.com → Seguridad → Verificación en 2 pasos (actívala si no la tienes)
  2. Ve a myaccount.google.com → Seguridad → Contraseñas de aplicaciones
  3. Crea una contraseña para "TechHoy Bot" → copia los 16 caracteres
  4. Añade al .env:
       NOTIFY_EMAIL_FROM=tu@gmail.com
       NOTIFY_EMAIL_TO=tu@gmail.com          (puede ser el mismo)
       NOTIFY_EMAIL_PASSWORD=abcd efgh ijkl mnop

Si no está configurado, las notificaciones se omiten silenciosamente.
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from src.utils.logger import get_logger

logger = get_logger("notify")


def _is_configured() -> bool:
    return bool(
        os.getenv("NOTIFY_EMAIL_FROM")
        and os.getenv("NOTIFY_EMAIL_PASSWORD")
        and os.getenv("NOTIFY_EMAIL_TO")
    )


def send(subject: str, body: str) -> None:
    """Send an email. Silently skips if not configured."""
    if not _is_configured():
        return

    sender = os.environ["NOTIFY_EMAIL_FROM"]
    recipient = os.environ["NOTIFY_EMAIL_TO"]
    password = os.environ["NOTIFY_EMAIL_PASSWORD"]

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"TechHoy Bot <{sender}>"
        msg["To"] = recipient
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())

        logger.info("Email sent: %s", subject)
    except Exception as exc:
        # Notification failure must never crash the pipeline
        logger.warning("Email notification failed: %s", exc)


def notify_success(channel_name: str, title: str, url: str) -> None:
    send(
        subject=f"✅ TechHoy — Vídeo publicado: {title[:50]}",
        body=(
            f"Canal: {channel_name}\n"
            f"Título: {title}\n"
            f"URL: {url}\n\n"
            f"El pipeline finalizó correctamente."
        ),
    )


def notify_error(channel_name: str, step: str, error: str) -> None:
    send(
        subject=f"❌ TechHoy — Error en pipeline ({step})",
        body=(
            f"Canal: {channel_name}\n"
            f"Paso fallido: {step}\n\n"
            f"Error:\n{error[:1000]}"
        ),
    )


def notify_start(channel_name: str, topic: str) -> None:
    send(
        subject=f"🚀 TechHoy — Pipeline iniciado",
        body=(
            f"Canal: {channel_name}\n"
            f"Tema seleccionado: {topic[:200]}\n\n"
            f"El vídeo estará listo en aproximadamente 40-60 minutos."
        ),
    )
