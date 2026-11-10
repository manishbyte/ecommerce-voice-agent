from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.business_rules import ORDER_STATUSES
from app.database.base import Base, JSONType

_status_list = ",".join(f"'{s}'" for s in sorted(ORDER_STATUSES))


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        # target for composite FKs: guarantees child rows reference an order *of the same customer*
        UniqueConstraint("id", "customer_pk", name="uq_orders_id_customer"),
        CheckConstraint(f"order_status IN ({_status_list})", name="order_status_valid"),
        CheckConstraint("total_amount >= 0", name="total_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # ORD1001
    customer_pk: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    order_date: Mapped[date] = mapped_column(Date)
    order_status: Mapped[str] = mapped_column(String(20), index=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    shipping_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    shipping_address: Mapped[dict] = mapped_column(JSONType)
    estimated_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivered_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    tracking_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    carrier: Mapped[str | None] = mapped_column(String(40), nullable=True)
    scenario_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", order_by="OrderItem.order_item_id")
    payments = relationship("Payment", back_populates="order", order_by="Payment.payment_id",
                            primaryjoin="Order.id == Payment.order_pk", foreign_keys="Payment.order_pk")
