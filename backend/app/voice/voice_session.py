"""Backend-owned realtime voice session.

Browser (any device with a mic) <--WebSocket--> FastAPI <--> Gnani STT / LangGraph / Gnani TTS

Protocol
  browser -> server : binary = PCM s16le mono 16 kHz audio frames
                      JSON  = {type: text|select_language|playback_done|stop|ping, ...}
  server -> browser : binary = PCM s16le mono TTS audio (preceded by audio_start, followed by audio_end)
                      JSON  = {type: transcript|status|language|event|audio_start|audio_end|error|...}

The session is half-duplex: mic frames are ignored while the agent is speaking (prevents the agent
hearing itself on speakers); the browser reports `playback_done` when playback finishes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import func, select

from app.agents.graph import SAFE_ERROR, run_turn, summarize_turn
from app.core.logging import bus, emit_event
from app.database.base import utcnow
from app.database.connection import get_sessionmaker
from app.models import Conversation, Message
from app.schemas.voice import ClientMessage
from app.voice.audio_config import MAX_CLIENT_AUDIO_FRAME, tts_sample_rate
from app.voice.language_config import DEFAULT_LANGUAGE, LanguageConfig, get_language
from app.voice.stt import STTSession, STTUnavailable, stt_available
from app.voice.tts import synthesize_pcm, tts_available

log = logging.getLogger(__name__)
ACTIVE_SESSIONS: dict[str, "VoiceSession"] = {}
_CLOSE = object()


class VoiceSession:
    def __init__(self, ws: WebSocket, conversation_id: str, graph):
        self.ws, self.cid, self.graph = ws, conversation_id, graph
        self.turn_q: asyncio.Queue = asyncio.Queue()
        self.stt: STTSession | None = None
        self.stt_task: asyncio.Task | None = None
        self.lang: LanguageConfig = get_language(DEFAULT_LANGUAGE)
        self.agent_speaking = False
        self.closing = False
        self._send_lock = asyncio.Lock()
        self._tasks: list[asyncio.Task] = []
        self._release: asyncio.Task | None = None
        self._stt_restarts = 0

    # ------------------------------------------------------------------ plumbing
    async def _send(self, payload: dict) -> bool:
        try:
            async with self._send_lock:
                await self.ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))
            return True
        except Exception:  # noqa: BLE001  (socket closed)
            return False

    async def _status(self, state: str) -> None:
        await self._send({"type": "status", "state": state})

    # ------------------------------------------------------------------ lifecycle
    async def run(self) -> None:
        ACTIVE_SESSIONS[self.cid] = self
        q = bus.subscribe(self.cid)
        self._tasks = [asyncio.create_task(self._forward_events(q)), asyncio.create_task(self._turn_worker())]
        try:
            await self._send({"type": "connected", "conversation_id": self.cid,
                              "providers": {"stt": stt_available(), "tts": tts_available()}})
            await self._bootstrap()
            await self._receive_loop()
        except WebSocketDisconnect:
            pass
        finally:
            await self._cleanup(q)

    async def _bootstrap(self) -> None:
        async with get_sessionmaker()() as s:
            conv = await s.get(Conversation, uuid.UUID(self.cid))
            n = (await s.execute(select(func.count(Message.id)).where(Message.conversation_pk == conv.id))).scalar_one()
            recent = (await s.execute(select(Message).where(Message.conversation_pk == conv.id)
                                      .order_by(Message.created_at.desc()).limit(10))).scalars().all()
        await self._configure_voice(conv.selected_language)
        if n == 0:
            await emit_event(self.cid, "conversation_started", agent="voice", summary="Voice session started")
            await self.turn_q.put(None)                         # greeting + language question
        else:
            await self._send({"type": "resumed", "messages": [{"role": m.role, "text": m.content} for m in reversed(recent)]})
            await self._status("listening")

    async def _receive_loop(self) -> None:
        while True:
            msg = await self.ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes") is not None:
                await self._on_audio(msg["bytes"])
            elif msg.get("text") is not None:
                if await self._on_text(msg["text"]):
                    return

    async def _on_audio(self, data: bytes) -> None:
        if self.agent_speaking or self.stt is None or len(data) > MAX_CLIENT_AUDIO_FRAME:
            return
        try:
            await self.stt.send_audio(data)
        except Exception as exc:  # noqa: BLE001
            log.warning("STT send failed: %s", exc)
            await self._restart_stt()

    async def _on_text(self, raw: str) -> bool:
        try:
            m = ClientMessage.model_validate_json(raw)
        except ValidationError:
            await self._send({"type": "error", "message": "invalid message"})
            return False
        if m.type == "ping":
            await self._send({"type": "pong"})
        elif m.type == "playback_done":
            self._release_speaking()
        elif m.type == "text" and m.text and m.text.strip():
            await self._submit_user_text(m.text.strip())
        elif m.type == "select_language" and m.language:
            initialized = self.lang_selected
            await self._submit_user_text(m.language if not initialized else f"please switch to {m.language}", echo=m.language)
        elif m.type == "stop":
            await self._end_conversation()
            return True
        return False

    @property
    def lang_selected(self) -> bool:
        return getattr(self, "_lang_selected", False)

    async def _end_conversation(self) -> None:
        async with get_sessionmaker()() as s:
            async with s.begin():
                conv = await s.get(Conversation, uuid.UUID(self.cid))
                conv.status, conv.ended_at = "ended", utcnow()
        await emit_event(self.cid, "conversation_ended", agent="voice", summary="Conversation ended")
        await self._send({"type": "ended"})

    async def _cleanup(self, q) -> None:
        self.closing = True
        await self.turn_q.put(_CLOSE)
        for t in [self.stt_task, self._release, *self._tasks]:
            if t and not t.done():
                t.cancel()
        if self.stt:
            await self.stt.close()
        bus.unsubscribe(self.cid, q)
        ACTIVE_SESSIONS.pop(self.cid, None)

    async def shutdown(self) -> None:
        """Called on application shutdown."""
        try:
            await self._send({"type": "server_shutdown"})
            await self.ws.close(code=1001)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ language / STT
    async def _configure_voice(self, language_key: str | None) -> None:
        cfg = get_language(language_key) or get_language(DEFAULT_LANGUAGE)
        self._lang_selected = bool(language_key)
        changed = cfg.key != self.lang.key or self.stt is None
        self.lang = cfg
        if changed:
            await self._restart_stt()
        await self._send({"type": "language", "key": cfg.key, "name": cfg.name, "stt_locale": cfg.stt_locale,
                          "tts_voice": cfg.tts_voice, "selected": self._lang_selected})
        await emit_event(self.cid, "voice_configured", agent="voice",
                         summary=f"STT {cfg.stt_locale} / TTS {cfg.tts_voice}", data={"language": cfg.key})

    async def _restart_stt(self) -> None:
        if self.stt_task and not self.stt_task.done():
            self.stt_task.cancel()
        if self.stt:
            await self.stt.close()
            self.stt = None
        if self.closing or not stt_available():
            if not stt_available():
                await self._send({"type": "stt_unavailable", "message": "Speech recognition is not configured; use typed input."})
            return
        sess = STTSession(self.lang.stt_locale)
        try:
            await sess.start()
        except Exception as exc:  # noqa: BLE001
            log.warning("STT start failed: %s", exc)
            await self._send({"type": "error", "message": "Could not start speech recognition", "recoverable": True})
            return
        self.stt = sess
        self.stt_task = asyncio.create_task(self._stt_consume(sess))

    async def _stt_consume(self, sess: STTSession) -> None:
        try:
            async for ev in sess.events():
                if ev["type"] == "processing":
                    await self._status("transcribing")
                elif ev["type"] == "transcript":
                    text = (ev["text"] or "").strip()
                    if text and not self.agent_speaking:
                        self._stt_restarts = 0
                        await self._submit_user_text(text, latency=ev.get("latency_ms"))
                elif ev["type"] == "error":
                    await self._send({"type": "error", "message": ev["message"], "recoverable": True})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("STT stream ended: %s", exc)
        if not self.closing and not sess.closed and self._stt_restarts < 3:   # server dropped us: reconnect
            self._stt_restarts += 1
            await asyncio.sleep(0.5 * self._stt_restarts)
            await self._restart_stt()

    # ------------------------------------------------------------------ turns
    async def _submit_user_text(self, text: str, *, echo: str | None = None, latency=None) -> None:
        await self._send({"type": "transcript", "role": "customer", "text": echo or text, "final": True,
                          "stt_latency_ms": latency})
        await self.turn_q.put(text)

    async def _finish_call(self) -> None:
        for _ in range(300):                      # let the goodbye finish playing (max ~30 s)
            if not self.agent_speaking:
                break
            await asyncio.sleep(0.1)
        await self._send({"type": "ended"})
        await emit_event(self.cid, "conversation_ended", agent="voice", summary="Ended by customer (goodbye)")
        try:
            await self.ws.close(code=1000)
        except Exception:
            pass

    async def _turn_worker(self) -> None:
        while True:
            item = await self.turn_q.get()
            if item is _CLOSE:
                return
            if isinstance(item, tuple) and item[0] == "say":      # server-initiated announcement
                await self._say(item[1])
                continue
            await self._status("thinking")
            try:
                final = await run_turn(self.graph, self.cid, item)
                r = summarize_turn(final)
                print(type(r), r)
                reply = r["response"] or SAFE_ERROR
            except Exception:  # noqa: BLE001
                log.exception("turn failed")
                r, reply = {"language": None, "language_changed": False, "pending_action": None, "intent": None}, SAFE_ERROR
            if r.get("language_changed") or (r.get("language") and r["language"] != self.lang.key):
                await self._configure_voice(r.get("language"))
            await self._send({"type": "transcript", "role": "agent", "text": reply, "final": True,
                              "intent": r.get("intent"), "pending_action": r.get("pending_action")})
            await self._speak(reply)
            if r.get("end_call"):
                await self._finish_call()

    async def announce(self, text: str) -> None:
        """Speak a server-side message (e.g. result of a REST confirm-action) into the live call."""
        await self.turn_q.put(("say", text))

    async def _say(self, text: str) -> None:
        await self._send({"type": "transcript", "role": "agent", "text": text, "final": True})
        await self._speak(text)

    # ------------------------------------------------------------------ TTS
    def _release_speaking(self) -> None:
        self.agent_speaking = False
        if self._release and not self._release.done():
            self._release.cancel()
        asyncio.create_task(self._status("listening"))

    async def _speak(self, text: str) -> None:
        if not tts_available():
            await self._send({"type": "tts_unavailable", "message": "Voice output is not configured; showing text only."})
            await self._status("listening")
            return
        await emit_event(self.cid, "tts_started", agent="voice", summary=f"Speaking ({self.lang.tts_voice})")
        self.agent_speaking = True
        await self._status("speaking")
        sr, total = tts_sample_rate(), 0
        await self._send({"type": "audio_start", "sample_rate": sr, "format": "pcm_s16le"})
        try:
            async for chunk in synthesize_pcm(text, self.lang):
                total += len(chunk)
                async with self._send_lock:
                    await self.ws.send_bytes(chunk)
        except Exception as exc:  # noqa: BLE001
            log.warning("TTS failed: %s", exc)
            await self._send({"type": "error", "message": "Voice output failed; showing text only.", "recoverable": True})
        await self._send({"type": "audio_end"})
        seconds = total / (2 * sr) + 3.0                           # safety net if the client never confirms
        self._release = asyncio.create_task(self._release_later(seconds))

    async def _release_later(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
        self.agent_speaking = False
        await self._status("listening")

    # ------------------------------------------------------------------ events
    async def _forward_events(self, q: asyncio.Queue) -> None:
        while True:
            ev = await q.get()
            await self._send({"type": "event", **ev})
