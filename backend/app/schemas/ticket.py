from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.core.business_rules import TICKET_STATUSES
from app.utils.formatting import iso


class TicketSeed(BaseModel):
    ticket_id: str
    customer_id: str
    order_id: str | None = None
    category: str
    subject: str
    description: str
    ticket_status: str
    priority: str = "medium"
    created_at: datetime
    updated_at: datetime
    resolution: str | None = None

    def model_post_init(self, _ctx) -> None:
        if self.ticket_status not in TICKET_STATUSES:
            raise ValueError(f"unknown ticket_status {self.ticket_status}")


def ticket_out(t, order_id: str | None, customer_id: str) -> dict:
    return {"ticket_id": t.ticket_id, "customer_id": customer_id, "order_id": order_id, "category": t.category,
            "subject": t.subject, "description": t.description, "ticket_status": t.ticket_status,
            "priority": t.priority, "source": t.source, "created_at": iso(t.created_at),
            "updated_at": iso(t.updated_at), "resolution": t.resolution}
