"""Gnani realtime STT wrapper (one locale per session, async, concurrent send/receive)."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.config import get_settings
from app.voice.audio_config import STT_FRAME_BYTES, STT_SAMPLE_RATE

log = logging.getLogger(__name__)
ITN_LOCALES = {"hi-IN", "en-IN"}   # inverse text normalisation is only supported for these (Gnani docs)


class STTUnavailable(RuntimeError):
    pass


def stt_available() -> bool:
    if not get_settings().gnani_api_key:
        return False
    try:
        import gnani.stt  # noqa: F401
        return True
    except ImportError:
        return False


class STTSession:
    def __init__(self, locale: str):
        self.locale = locale
        self._client = None
        self._buf = bytearray()
        self.closed = False

    async def start(self) -> None:
        if not stt_available():
            raise STTUnavailable("Gnani STT is not configured (GNANI_API_KEY / gnani-vachana)")
        from gnani.stt import GnaniSTTStreamClient

        self._client = GnaniSTTStreamClient(
            api_key=get_settings().gnani_api_key, language_code=self.locale, sample_rate=STT_SAMPLE_RATE,
            format="transcribe" if self.locale in ITN_LOCALES else "verbatim")
        await self._client.connect()
        log.info("STT connected (%s)", self.locale)

    async def send_audio(self, pcm: bytes) -> None:
        """Accepts arbitrary PCM sizes; forwards exact 1,024-byte frames as the API requires."""
        if self.closed or self._client is None:
            return
        self._buf.extend(pcm)
        while len(self._buf) >= STT_FRAME_BYTES:
            frame = bytes(self._buf[:STT_FRAME_BYTES])
            del self._buf[:STT_FRAME_BYTES]
            await self._client.send_audio(frame)

    async def events(self) -> AsyncIterator[dict]:
        from gnani.stt import StreamErrorEvent, StreamProcessingEvent, StreamTranscriptEvent

        async for ev in self._client:
            if isinstance(ev, StreamTranscriptEvent):
                yield {"type": "transcript", "text": ev.text, "latency_ms": getattr(ev, "latency", None)}
            elif isinstance(ev, StreamProcessingEvent):
                yield {"type": "processing"}
            elif isinstance(ev, StreamErrorEvent):
                yield {"type": "error", "message": ev.message}

    async def close(self) -> None:
        self.closed = True
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as exc:  # noqa: BLE001
                log.debug("STT close: %s", exc)
            self._client = None
