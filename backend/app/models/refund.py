from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.business_rules import REFUND_STATUSES
from app.database.base import Base, utcnow

_rs = ",".join(f"'{s}'" for s in sorted(REFUND_STATUSES))


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        # refund must reference a payment that belongs to the same order AND the same customer
        ForeignKeyConstraint(["payment_pk", "order_pk", "customer_pk"],
                             ["payments.id", "payments.order_pk", "payments.customer_pk"],
                             name="fk_refunds_payment_order_customer"),
        CheckConstraint(f"refund_status IN ({_rs})", name="refund_status_valid"),
        CheckConstraint("refund_amount > 0", name="refund_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    refund_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # REF1001
    payment_pk: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    order_pk: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    customer_pk: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    refund_status: Mapped[str] = mapped_column(String(20), index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    estimated_completion_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    payment = relationship("Payment", back_populates="refunds", foreign_keys=[payment_pk],
                           primaryjoin="Refund.payment_pk == Payment.id")
    order = relationship("Order", foreign_keys=[order_pk], primaryjoin="Refund.order_pk == Order.id")
