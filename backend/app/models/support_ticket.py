from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.business_rules import TICKET_STATUSES
from app.database.base import Base, utcnow

_ts = ",".join(f"'{s}'" for s in sorted(TICKET_STATUSES))


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    __table_args__ = (
        # order_pk is nullable (general tickets); when present it must belong to the same customer
        ForeignKeyConstraint(["order_pk", "customer_pk"], ["orders.id", "orders.customer_pk"],
                             name="fk_tickets_order_customer"),
        CheckConstraint(f"ticket_status IN ({_ts})", name="ticket_status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # TKT1001
    customer_pk: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    order_pk: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    conversation_pk: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    ticket_status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(10), default="medium")
    source: Mapped[str] = mapped_column(String(20), default="seed")  # seed | voice_agent
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)

    customer = relationship("Customer", back_populates="tickets")
    order = relationship("Order", foreign_keys=[order_pk], primaryjoin="SupportTicket.order_pk == Order.id")
