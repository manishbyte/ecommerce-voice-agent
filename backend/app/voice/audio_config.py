"""Audio format constants. STT input is raw PCM s16le mono; TTS output is raw PCM s16le mono."""
from __future__ import annotations

from app.config import get_settings

STT_SAMPLE_RATE = 16000
STT_FRAME_SAMPLES = 512          # 32 ms @ 16 kHz (Gnani docs)
STT_FRAME_BYTES = STT_FRAME_SAMPLES * 2
MAX_CLIENT_AUDIO_FRAME = 64 * 1024


def tts_sample_rate() -> int:
    return get_settings().tts_sample_rate


def tts_audio_config():
    """Raw (header-less) 16-bit mono PCM so chunks can be scheduled for gapless playback in the browser."""
    from gnani.tts import AudioConfig

    return AudioConfig(sample_rate=tts_sample_rate(), encoding="linear_pcm", container="raw")
