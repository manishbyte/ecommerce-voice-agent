from __future__ import annotations

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    customer_id: str | None = Field(default=None, max_length=20)


class ConfirmActionRequest(BaseModel):
    action_id: str | None = None
    decision: str = Field(pattern="^(confirm|reject)$")


class ConversationOut(BaseModel):
    conversation_id: str
    customer_id: str | None
    customer_verified: bool
    selected_language: str | None
    status: str
    resolution_status: str
    started_at: str
    ended_at: str | None = None
    websocket_path: str
