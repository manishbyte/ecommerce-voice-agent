from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ClientMessage(BaseModel):
    """JSON control messages sent by the browser over the voice WebSocket (audio is binary)."""

    type: Literal["text", "select_language", "playback_done", "stop", "ping"]
    text: str | None = Field(default=None, max_length=2000)
    language: str | None = Field(default=None, max_length=40)
