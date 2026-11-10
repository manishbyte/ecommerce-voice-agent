"""Gnani realtime TTS (timbre-v2.5) streaming wrapper."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.config import get_settings
from app.utils.formatting import clean_for_speech
from app.voice.audio_config import tts_audio_config
from app.voice.language_config import LanguageConfig

log = logging.getLogger(__name__)


def tts_available() -> bool:
    if not get_settings().gnani_api_key:
        return False
    try:
        import gnani.tts  # noqa: F401
        return True
    except ImportError:
        return False


async def synthesize_pcm(text: str, cfg: LanguageConfig) -> AsyncIterator[bytes]:
    """Yield raw PCM chunks as they are generated (model is always passed explicitly)."""
    from gnani.tts import GnaniTTSRealtimeClient

    s = get_settings()
    async with GnaniTTSRealtimeClient(api_key=s.gnani_api_key) as client:
        async for chunk in client.synthesize(clean_for_speech(text), voice=cfg.tts_voice, model=s.gnani_tts_model,
                                             language=cfg.tts_language, audio_config=tts_audio_config()):
            if chunk:
                yield chunk
