import json

import pytest

from app.voice import stt as stt_mod
from app.voice.client_page import render_client_page
from app.voice.stt import STTSession, STTUnavailable, stt_available
from app.voice.tts import tts_available


class FakeWS:
    def __init__(self):
        self.texts, self.bytes = [], []

    async def send_text(self, t): self.texts.append(json.loads(t))
    async def send_bytes(self, b): self.bytes.append(b)


def test_providers_unavailable_without_keys():
    assert not stt_available() and not tts_available()


async def test_stt_start_fails_cleanly_without_key():
    with pytest.raises(STTUnavailable):
        await STTSession("en-IN").start()


async def test_stt_rechunks_audio_into_exact_1024_byte_frames():
    sent = []

    class Fake:
        async def send_audio(self, b): sent.append(len(b))

    s = STTSession("hi-IN")
    s._client = Fake()
    for n in (300, 900, 2000, 5):                 # arbitrary browser frame sizes
        await s.send_audio(b"\x00" * n)
    assert sent and set(sent) == {1024} and len(sent) == (300 + 900 + 2000 + 5) // 1024
    assert stt_mod.ITN_LOCALES == {"hi-IN", "en-IN"}


async def test_tts_audio_is_streamed_progressively(monkeypatch, db, make_conversation):
    from app.voice import voice_session as vs

    async def fake_synth(text, cfg):
        for _ in range(3):
            yield b"\x01\x00" * 100
    monkeypatch.setattr(vs, "tts_available", lambda: True)
    monkeypatch.setattr(vs, "synthesize_pcm", fake_synth)
    ws = FakeWS()
    session = vs.VoiceSession(ws, await make_conversation("CUS1001"), graph=None)
    await session._speak("hello")
    kinds = [m["type"] for m in ws.texts]
    assert "audio_start" in kinds and "audio_end" in kinds and len(ws.bytes) == 3
    assert session.agent_speaking                    # half-duplex until the browser reports playback_done
    session._release_speaking()
    assert not session.agent_speaking
    session._release and session._release.cancel()


async def test_audio_frames_ignored_while_agent_speaks(db, make_conversation):
    from app.voice.voice_session import VoiceSession

    got = []

    class FakeSTT:
        async def send_audio(self, b): got.append(b)

    s = VoiceSession(FakeWS(), await make_conversation("CUS1001"), graph=None)
    s.stt = FakeSTT()
    await s._on_audio(b"\x00" * 1024)
    s.agent_speaking = True
    await s._on_audio(b"\x00" * 1024)
    assert len(got) == 1


def test_browser_client_supports_any_device():
    page = render_client_page()
    for marker in ("getUserMedia", "isSecureContext", "AudioWorklet", "createScriptProcessor", "playback_done",
                   "viewport", "/api/voice/", "webkitAudioContext"):
        assert marker in page
