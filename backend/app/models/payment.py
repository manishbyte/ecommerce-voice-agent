from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.business_rules import PAYMENT_STATUSES
from app.database.base import Base

_ps = ",".join(f"'{s}'" for s in sorted(PAYMENT_STATUSES))


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        ForeignKeyConstraint(["order_pk", "customer_pk"], ["orders.id", "orders.customer_pk"],
                             name="fk_payments_order_customer"),
        UniqueConstraint("id", "order_pk", "customer_pk", name="uq_payments_id_order_customer"),
        CheckConstraint(f"payment_status IN ({_ps})", name="payment_status_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # PAY1001
    order_pk: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    customer_pk: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    payment_method: Mapped[str] = mapped_column(String(30))
    transaction_reference: Mapped[str] = mapped_column(String(40), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    payment_status: Mapped[str] = mapped_column(String(20), index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    order = relationship("Order", back_populates="payments", foreign_keys=[order_pk],
                         primaryjoin="Payment.order_pk == Order.id")
    refunds = relationship("Refund", back_populates="payment", order_by="Refund.refund_id",
                           primaryjoin="Payment.id == Refund.payment_pk", foreign_keys="Refund.payment_pk")
