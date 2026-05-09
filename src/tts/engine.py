"""
Text-to-Speech engine — provider options:
  - edge   (default): Microsoft Edge TTS — FREE, neural voices, no API key
  - gtts             : Google Translate TTS — FREE, lower quality
  - google           : Google Cloud TTS Neural2 — free up to 1M chars/month (needs billing)
  - openai           : OpenAI TTS-1 — ~$15/1M chars

Provider is selected via TTS_PROVIDER env var (default: edge).
"""
import asyncio
import os
import uuid
from pathlib import Path

from src.utils.logger import get_logger
from src.utils.retry import with_retry

logger = get_logger("tts")

# Edge TTS voices — neural quality, completely free
_EDGE_VOICES = {
    "es": "es-ES-AlvaroNeural",   # Spanish male, natural and clear
    "en": "en-US-GuyNeural",
}

_GOOGLE_VOICES = {
    "es": {"language_code": "es-ES", "name": "es-ES-Neural2-B"},
    "en": {"language_code": "en-US", "name": "en-US-Neural2-D"},
}

_OPENAI_VOICES = {
    "es": "onyx",
    "en": "onyx",
}

_GTTS_LANG = {
    "es": "es",
    "en": "en",
}


@with_retry(max_attempts=3, base_delay=2.0)
def synthesize(text: str, language: str, output_dir: str) -> str:
    """
    Converts text to an MP3 audio file.
    Returns the path to the generated audio file.
    """
    provider = os.getenv("TTS_PROVIDER", "edge").lower()
    output_path = str(Path(output_dir) / f"audio_{uuid.uuid4().hex[:8]}.mp3")

    logger.info("Synthesizing %d characters with provider '%s'…", len(text), provider)

    if provider == "edge":
        _synthesize_edge(text, language, output_path)
    elif provider == "gtts":
        _synthesize_gtts(text, language, output_path)
    elif provider == "google":
        _synthesize_google(text, language, output_path)
    elif provider == "openai":
        _synthesize_openai(text, language, output_path)
    else:
        raise ValueError(f"Unknown TTS_PROVIDER: '{provider}'. Use 'edge', 'gtts', 'google', or 'openai'.")

    size_kb = Path(output_path).stat().st_size // 1024
    logger.info("Audio saved: %s (%d KB)", output_path, size_kb)
    return output_path


def _synthesize_edge(text: str, language: str, output_path: str) -> None:
    """
    Microsoft Edge TTS — free neural voices, no API key needed.
    Quality is significantly better than gTTS.
    """
    import edge_tts

    voice = _EDGE_VOICES.get(language.lower()[:2], _EDGE_VOICES["es"])

    async def _run():
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)

    asyncio.run(_run())


def _synthesize_gtts(text: str, language: str, output_path: str) -> None:
    from gtts import gTTS
    import io

    lang = _GTTS_LANG.get(language.lower()[:2], "es")
    chunks = _chunk_text(text, max_bytes=3000)
    all_audio = b""

    for i, chunk in enumerate(chunks):
        logger.debug("gTTS chunk %d/%d (%d chars)…", i + 1, len(chunks), len(chunk))
        tts = gTTS(text=chunk, lang=lang, slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        all_audio += buf.getvalue()

    with open(output_path, "wb") as f:
        f.write(all_audio)


def _synthesize_google(text: str, language: str, output_path: str) -> None:
    from google.cloud import texttospeech

    lang_key = language.lower()[:2]
    voice_cfg = _GOOGLE_VOICES.get(lang_key, _GOOGLE_VOICES["en"])
    client = texttospeech.TextToSpeechClient()

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

    chunks = _chunk_text(text, max_bytes=4800)
    audio_data = b""

    for i, chunk in enumerate(chunks):
        logger.debug("Google TTS chunk %d/%d (%d chars)", i + 1, len(chunks), len(chunk))
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
    voice = os.getenv("OPENAI_TTS_VOICE") or _OPENAI_VOICES.get(lang_key, "onyx")
    model = os.getenv("OPENAI_TTS_MODEL", "tts-1")
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    chunks = _chunk_text(text, max_bytes=4000)
    all_audio = b""

    for i, chunk in enumerate(chunks):
        logger.debug("OpenAI TTS chunk %d/%d", i + 1, len(chunks))
        response = client.audio.speech.create(
            model=model, voice=voice, input=chunk, response_format="mp3"
        )
        all_audio += response.content

    with open(output_path, "wb") as f:
        f.write(all_audio)


def _chunk_text(text: str, max_bytes: int = 3000) -> list:
    """Split text on sentence boundaries without exceeding max_bytes."""
    if len(text.encode("utf-8")) <= max_bytes:
        return [text]

    sentences = (
        text.replace("? ", "?|||")
            .replace("! ", "!|||")
            .replace(". ", ".|||")
            .split("|||")
    )
    chunks, current = [], ""

    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate.encode("utf-8")) > max_bytes:
            if current:
                chunks.append(current.strip())
            current = sentence
        else:
            current = candidate

    if current.strip():
        chunks.append(current.strip())

    return chunks or [text[:max_bytes]]
