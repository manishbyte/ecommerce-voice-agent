from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core import business_rules as rules
from app.core.exceptions import NotFoundError
from app.database.base import utcnow
from app.database.connection import get_sessionmaker
from app.guardrails.customer_authorization import get_owned_order
from app.models import Customer, Order, OrderItem, Payment, Refund
from app.schemas.order import order_out
from app.schemas.payment import payment_out
from app.tools import fail, ok
from app.utils.formatting import iso, num

_STOP = {"the", "my", "a", "an", "of", "order", "orders", "item", "product", "one", "for", "and", "please", "about",
         "where", "is", "what", "status", "ka", "ki", "ke", "mera", "meri", "mere", "ek", "wala", "wali"}


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 2 and t not in _STOP]


async def get_customer_orders(customer_id: str, limit: int = 20) -> dict:
    async with get_sessionmaker()() as s:
        rows = (await s.execute(
            select(Order).join(Customer, Customer.id == Order.customer_pk)
            .where(Customer.customer_id == customer_id)
            .options(joinedload(Order.customer), selectinload(Order.items).joinedload(OrderItem.product))
            .order_by(Order.order_date.desc(), Order.order_id.desc()).limit(limit))).scalars().all()
        return ok([order_out(o) for o in rows], count=len(rows))


async def get_order_details(customer_id: str, order_id: str) -> dict:
    async with get_sessionmaker()() as s:
        try:
            o = await get_owned_order(s, customer_id, order_id)
        except NotFoundError:
            return fail("order_not_found", f"No order {order_id} was found on this account.")
        data = order_out(o)
        data["payments"] = [payment_out(p, o.order_id, customer_id) for p in o.payments]
        return ok(data)


async def get_order_tracking(customer_id: str, order_id: str) -> dict:
    async with get_sessionmaker()() as s:
        try:
            o = await get_owned_order(s, customer_id, order_id)
        except NotFoundError:
            return fail("order_not_found", f"No order {order_id} was found on this account.")
        today = date.today()
        overdue = (o.order_status in {"shipped", "delayed", "processing"} and o.estimated_delivery_date is not None
                   and o.estimated_delivery_date < today)
        return ok({"order_id": o.order_id, "order_status": o.order_status, "carrier": o.carrier,
                   "tracking_number": o.tracking_number, "estimated_delivery_date": iso(o.estimated_delivery_date),
                   "delivered_at": iso(o.delivered_at), "past_estimated_date": overdue,
                   "items": [i.product.name for i in o.items]})


async def find_orders_by_product(customer_id: str, query: str) -> dict:
    """Orders (of this customer) containing a product matching the query words."""
    toks = tokens(query)
    if not toks:
        return ok([], count=0)
    res = await get_customer_orders(customer_id, limit=50)
    hits = []
    for o in res["data"]:
        names = " ".join(i["product_name"].lower() for i in o["items"])
        cats = names
        score = sum(1 for t in toks if t in cats)
        if score:
            hits.append((score, o))
    hits.sort(key=lambda x: -x[0])
    best = [o for sc, o in hits if sc == (hits[0][0] if hits else 0)]
    return ok(best, count=len(best))


async def check_cancellation_eligibility(customer_id: str, order_id: str) -> dict:
    async with get_sessionmaker()() as s:
        try:
            o = await get_owned_order(s, customer_id, order_id)
        except NotFoundError:
            return fail("order_not_found", f"No order {order_id} was found on this account.")
        r = rules.check_cancellation(o.order_status)
        return ok({"order_id": o.order_id, "order_status": o.order_status, "eligible": r.eligible,
                   "reason_code": r.code, "reason": r.message})


# ---- action executors (called only from guardrails.action_confirmation, inside its transaction) ----
async def _next_refund_id(session: AsyncSession) -> str:
    last = (await session.execute(select(Refund.refund_id).order_by(Refund.refund_id.desc()).limit(1))).scalar_one_or_none()
    return f"REF{int(last[3:]) + 1}" if last else "REF1001"


async def revalidate_cancellation(session: AsyncSession, customer_id: str, params: dict) -> rules.RuleResult:
    o = await get_owned_order(session, customer_id, params["order_id"])
    return rules.check_cancellation(o.order_status)


async def execute_cancellation(session: AsyncSession, customer_id: str, params: dict) -> dict:
    o = await get_owned_order(session, customer_id, params["order_id"])
    r = rules.check_cancellation(o.order_status)
    if not r.eligible:
        raise ValueError(r.message)
    o.order_status = "cancelled"
    refund_info = None
    captured = [p for p in o.payments if p.payment_status == "captured" and not p.refunds]
    if captured:  # simulated refund record - no real payment gateway
        p = captured[0]
        ref = Refund(refund_id=await _next_refund_id(session), payment_pk=p.id, order_pk=o.id, customer_pk=o.customer_pk,
                     refund_amount=p.amount, currency=p.currency, refund_status="requested",
                     reason="Customer cancelled before dispatch (voice agent)", requested_at=utcnow(),
                     estimated_completion_date=rules.refund_estimated_completion(date.today()))
        session.add(ref)
        refund_info = {"refund_id": ref.refund_id, "amount": num(p.amount),
                       "estimated_completion_date": iso(ref.estimated_completion_date)}
    return {"order_id": o.order_id, "new_status": "cancelled", "refund": refund_info}


