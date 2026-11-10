from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, BigIntPK, utcnow


class ChangeLog(Base):
    """Append-only audit trail of edits: who changed what, when, old -> new."""

    __tablename__ = "change_log"
    __table_args__ = (Index("ix_change_log_customer_created", "customer_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(20))            # customer | order
    entity_id: Mapped[str] = mapped_column(String(20))              # CUS1001 / ORD1010
    customer_id: Mapped[str] = mapped_column(String(20), index=True)
    field: Mapped[str] = mapped_column(String(40))                  # full_name, email, ..., address, shipping_address, status, __created__
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20))                 # dashboard | voice_agent | demo_generator | system
    actor: Mapped[str] = mapped_column(String(80), default="recruiter")
    conversation_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
