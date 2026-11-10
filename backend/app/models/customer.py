from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, JSONType, utcnow


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # e.g. CUS1001
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    mobile_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    address: Mapped[dict] = mapped_column(JSONType)
    preferred_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    orders = relationship("Order", back_populates="customer", order_by="Order.order_date")
    tickets = relationship("SupportTicket", back_populates="customer", order_by="SupportTicket.created_at")
    conversations = relationship("Conversation", back_populates="customer")
