from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.core.business_rules import PAYMENT_STATUSES
from app.utils.formatting import iso, num


class PaymentSeed(BaseModel):
    payment_id: str
    order_id: str
    customer_id: str
    payment_method: str
    transaction_reference: str
    amount: Decimal
    currency: str = "INR"
    payment_status: str
    paid_at: datetime | None = None

    def model_post_init(self, _ctx) -> None:
        if self.payment_status not in PAYMENT_STATUSES:
            raise ValueError(f"unknown payment_status {self.payment_status}")


def payment_out(p, order_id: str, customer_id: str) -> dict:
    return {"payment_id": p.payment_id, "order_id": order_id, "customer_id": customer_id,
            "payment_method": p.payment_method, "transaction_reference": p.transaction_reference,
            "amount": num(p.amount), "currency": p.currency, "payment_status": p.payment_status,
            "paid_at": iso(p.paid_at)}
