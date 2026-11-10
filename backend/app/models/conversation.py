from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, BigIntPK, JSONType, utcnow


class Conversation(Base):
    """One voice support session. `str(id)` is also the LangGraph thread_id."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    customer_pk: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    selected_language: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")            # active | ended
    resolution_status: Mapped[str] = mapped_column(String(20), default="unresolved")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    customer = relationship("Customer", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at")


class PendingAction(Base):
    """A proposed support action awaiting explicit customer confirmation (DB is authoritative)."""

    __tablename__ = "pending_actions"
    __table_args__ = (Index("ix_pending_conv_status", "conversation_pk", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_pk: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    customer_pk: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    action_type: Mapped[str] = mapped_column(String(30))
    params: Mapped[dict] = mapped_column(JSONType)
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|executed|rejected|expired|superseded|failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONType, nullable=True)


class ConversationEvent(Base):
    """Structured agent-execution events shown in the recruiter's agent monitor."""

    __tablename__ = "conversation_events"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    conversation_pk: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    agent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    summary: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
