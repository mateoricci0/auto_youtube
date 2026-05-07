"""
Text-to-Speech engine with two provider options:
  - google  (default): Google Cloud TTS Neural2 — free up to 1M chars/month
  - openai           : OpenAI TTS-1 — easier setup, ~$15/1M chars

Provider is selected via TTS_PROVIDER env var.
"""
import os
import uuid
from pathlib import Path
from typing import Dict

from src.utils.logger import get_logger
from src.utils.retry import with_retry

logger = get_logger("tts")

# Voice settings per language per provider
_GOOGLE_VOICES = {
    "es": {"language_code": "es-ES", "name": "es-ES-Neural2-B", "gender": "MALE"},
    "en": {"language_code": "en-US", "name": "en-US-Neural2-D", "gender": "MALE"},
}

_OPENAI_VOICES = {
    "es": "onyx",   # Deep, authoritative — works well for Spanish
    "en": "onyx",
}


@with_retry(max_attempts=3, base_delay=2.0)
def synthesize(text: str, language: str, output_dir: str) -> str:
    """
    Converts text to an MP3 audio file.
    Returns the path to the generated audio file.
    """
    provider = os.getenv("TTS_PROVIDER", "google").lower()
    output_path = str(Path(output_dir) / f"audio_{uuid.uuid4().hex[:8]}.mp3")

    logger.info("Synthesizing %d characters with provider '%s'...", len(text), provider)

    if provider == "google":
        _synthesize_google(text, language, output_path)
    elif provider == "openai":
        _synthesize_openai(text, language, output_path)
    else:
        raise ValueError(f"Unknown TTS_PROVIDER: {provider}. Use 'google' or 'openai'.")

    size_kb = Path(output_path).stat().st_size // 1024
    logger.info("Audio saved: %s (%d KB)", output_path, size_kb)
    return output_path


def _synthesize_google(text: str, language: str, output_path: str) -> None:
    from google.cloud import texttospeech

    lang_key = language.lower()[:2]
    voice_cfg = _GOOGLE_VOICES.get(lang_key, _GOOGLE_VOICES["en"])

    client = texttospeech.TextToSpeechClient()

    synthesis_input = texttospeech.SynthesisInput(text=text)

    voice = texttospeech.VoiceSelectionParams(
        language_code=voice_cfg["language_code"],
        name=voice_cfg["name"],
        ssml_gender=texttospeech.SsmlVoiceGender.MALE,
    )

    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.0,
        pitch=0.0,
    )

    # Google TTS has a 5000 byte limit per request — chunk for long texts
    chunks = _chunk_text(text, max_bytes=4800)
    audio_data = b""

    for i, chunk in enumerate(chunks):
        logger.debug("TTS chunk %d/%d (%d chars)", i + 1, len(chunks), len(chunk))
        synthesis_input = texttospeech.SynthesisInput(text=chunk)
        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )
        audio_data += response.audio_content

    with open(output_path, "wb") as f:
        f.write(audio_data)


def _synthesize_openai(text: str, language: str, output_path: str) -> None:
    from openai import OpenAI

    lang_key = language.lower()[:2]
    voice = _OPENAI_VOICES.get(lang_key, "onyx")
    model = os.getenv("OPENAI_TTS_MODEL", "tts-1")
    override_voice = os.getenv("OPENAI_TTS_VOICE")
    if override_voice:
        voice = override_voice

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # OpenAI TTS has a 4096 char limit per request
    chunks = _chunk_text(text, max_bytes=4000)
    all_audio = b""

    for i, chunk in enumerate(chunks):
        logger.debug("OpenAI TTS chunk %d/%d", i + 1, len(chunks))
        response = client.audio.speech.create(
            model=model,
            voice=voice,
            input=chunk,
            response_format="mp3",
        )
        all_audio += response.content

    with open(output_path, "wb") as f:
        f.write(all_audio)


def _chunk_text(text: str, max_bytes: int = 4800) -> list:
    """Split text into chunks that don't exceed max_bytes, splitting on sentences."""
    if len(text.encode("utf-8")) <= max_bytes:
        return [text]

    sentences = text.replace("? ", "?|||").replace("! ", "!|||").replace(". ", ".|||").split("|||")
    chunks = []
    current = ""

    for sentence in sentences:
        candidate = current + (" " if current else "") + sentence
        if len(candidate.encode("utf-8")) > max_bytes:
            if current:
                chunks.append(current.strip())
            current = sentence
        else:
            current = candidate

    if current.strip():
        chunks.append(current.strip())

    return chunks if chunks else [text[:max_bytes]]
