from __future__ import annotations

import uuid

from fastapi import APIRouter, WebSocket
from fastapi.responses import HTMLResponse

from app.database.connection import get_sessionmaker
from app.dependencies import resources
from app.models import Conversation
from app.voice.client_page import render_client_page
from app.voice.voice_session import VoiceSession

router = APIRouter(prefix="/voice", tags=["voice"])


@router.get("/client", response_class=HTMLResponse)
@router.get("/client/{conversation_id}", response_class=HTMLResponse)
async def voice_client(conversation_id: str | None = None) -> HTMLResponse:
    """Standalone browser voice client (laptop / phone / tablet). Open over HTTPS for microphone access."""
    return HTMLResponse(render_client_page(), headers={"Cache-Control": "no-store"})


@router.websocket("/{conversation_id}")
async def voice_socket(ws: WebSocket, conversation_id: str) -> None:
    await ws.accept()
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError:
        await ws.close(code=4404)
        return
    if resources.shutting_down or resources.graph is None:
        await ws.close(code=1013)
        return
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, cid)
    if conv is None or conv.status == "ended":
        await ws.close(code=4404)
        return
    await VoiceSession(ws, conversation_id, resources.graph).run()
