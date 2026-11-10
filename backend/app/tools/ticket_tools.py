from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config import get_settings
from app.core import business_rules as rules
from app.core.exceptions import NotFoundError
from app.database.base import utcnow
from app.database.connection import get_sessionmaker
from app.guardrails.customer_authorization import get_owned_order, resolve_customer
from app.models import Customer, Order, SupportTicket
from app.schemas.ticket import ticket_out
from app.tools import fail, ok


async def get_customer_tickets(customer_id: str, order_id: str | None = None, only_open: bool = False) -> dict:
    async with get_sessionmaker()() as s:
        q = (select(SupportTicket).join(Customer, Customer.id == SupportTicket.customer_pk)
             .where(Customer.customer_id == customer_id).options(joinedload(SupportTicket.order))
             .order_by(SupportTicket.created_at.desc()))
        if order_id:
            q = q.join(Order, Order.id == SupportTicket.order_pk).where(Order.order_id == order_id)
        if only_open:
            q = q.where(SupportTicket.ticket_status.in_(rules.OPEN_TICKET_STATUSES))
        rows = (await s.execute(q)).scalars().all()
        return ok([ticket_out(t, t.order.order_id if t.order else None, customer_id) for t in rows], count=len(rows))


async def check_return_eligibility(customer_id: str, order_id: str) -> dict:
    """Used for both return and replacement requests (same window)."""
    async with get_sessionmaker()() as s:
        try:
            o = await get_owned_order(s, customer_id, order_id)
        except NotFoundError:
            return fail("order_not_found", f"No order {order_id} was found on this account.")
        r = rules.check_return(o.order_status, o.delivered_at, date.today(), get_settings().return_window_days)
        return ok({"order_id": o.order_id, "order_status": o.order_status, "delivered_at": o.delivered_at.isoformat() if o.delivered_at else None,
                   "eligible": r.eligible, "reason_code": r.code, "reason": r.message})


async def _next_ticket_id(session: AsyncSession) -> str:
    last = (await session.execute(select(SupportTicket.ticket_id).order_by(SupportTicket.ticket_id.desc()).limit(1))).scalar_one_or_none()
    return f"TKT{int(last[3:]) + 1}" if last else "TKT1001"


async def revalidate_ticket(session: AsyncSession, customer_id: str, params: dict) -> rules.RuleResult:
    if params.get("category") not in rules.TICKET_CATEGORIES:
        return rules.RuleResult(False, "bad_category", "Unknown ticket category.")
    if params.get("order_id"):
        o = await get_owned_order(session, customer_id, params["order_id"])
        if params["category"] in {"return_request", "replacement_request"}:
            return rules.check_return(o.order_status, o.delivered_at, date.today(), get_settings().return_window_days)
        dup = (await session.execute(
            select(SupportTicket.ticket_id).where(SupportTicket.order_pk == o.id, SupportTicket.category == params["category"],
                                                  SupportTicket.ticket_status.in_(rules.OPEN_TICKET_STATUSES)))).first()
        if dup:
            return rules.RuleResult(False, "duplicate_ticket", f"An open {params['category']} ticket already exists for this order.")
    return rules.RuleResult(True, "eligible", "ok")


async def execute_create_ticket(session: AsyncSession, customer_id: str, params: dict, conversation_id: str | None) -> dict:
    cust = await resolve_customer(session, customer_id)
    order_pk = None
    order_id = params.get("order_id")
    if order_id:
        order_pk = (await get_owned_order(session, customer_id, order_id)).id
    tid = await _next_ticket_id(session)
    now = utcnow()
    session.add(SupportTicket(
        ticket_id=tid, customer_pk=cust.id, order_pk=order_pk, category=params["category"],
        subject=params["subject"][:200], description=params["description"][:1000], ticket_status="open",
        priority=params.get("priority", "medium"), source="voice_agent", created_at=now, updated_at=now,
        conversation_pk=uuid.UUID(conversation_id) if conversation_id else None))
    return {"ticket_id": tid, "order_id": order_id, "category": params["category"], "status": "open",
            "priority": params.get("priority", "medium")}
