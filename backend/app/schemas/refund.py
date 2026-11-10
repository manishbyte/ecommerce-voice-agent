from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.core.business_rules import REFUND_STATUSES
from app.utils.formatting import iso, num


class RefundSeed(BaseModel):
    refund_id: str
    order_id: str
    payment_id: str
    customer_id: str
    refund_amount: Decimal
    currency: str = "INR"
    refund_status: str
    reason: str | None = None
    requested_at: datetime
    processed_at: datetime | None = None
    estimated_completion_date: date | None = None

    def model_post_init(self, _ctx) -> None:
        if self.refund_status not in REFUND_STATUSES:
            raise ValueError(f"unknown refund_status {self.refund_status}")


def refund_out(r, order_id: str, payment_id: str, customer_id: str) -> dict:
    return {"refund_id": r.refund_id, "order_id": order_id, "payment_id": payment_id, "customer_id": customer_id,
            "refund_amount": num(r.refund_amount), "currency": r.currency, "refund_status": r.refund_status,
            "reason": r.reason, "requested_at": iso(r.requested_at), "processed_at": iso(r.processed_at),
            "estimated_completion_date": iso(r.estimated_completion_date)}
