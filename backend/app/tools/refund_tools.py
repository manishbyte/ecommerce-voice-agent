from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core import business_rules as rules
from app.core.exceptions import NotFoundError
from app.database.base import utcnow
from app.database.connection import get_sessionmaker
from app.guardrails.customer_authorization import get_owned_order
from app.models import Customer, Order, Payment, Refund
from app.schemas.refund import refund_out
from app.tools import fail, ok
from app.tools.order_tools import _next_refund_id
from app.utils.formatting import iso, num


async def get_refund_status(customer_id: str, order_id: str | None = None) -> dict:
    async with get_sessionmaker()() as s:
        q = (select(Refund).join(Customer, Customer.id == Refund.customer_pk).join(Order, Order.id == Refund.order_pk)
             .join(Payment, Payment.id == Refund.payment_pk).where(Customer.customer_id == customer_id)
             .options(joinedload(Refund.order), joinedload(Refund.payment)).order_by(Refund.refund_id))
        if order_id:
            q = q.where(Order.order_id == order_id)
        rows = (await s.execute(q)).scalars().all()
        if not rows:
            return fail("refund_not_found", "No refund records were found for that request.")
        return ok([refund_out(r, r.order.order_id, r.payment.payment_id, customer_id) for r in rows], count=len(rows))


def _evaluate(order: Order) -> tuple[rules.RuleResult, Payment | None]:
    captured = next((p for p in order.payments if p.payment_status == "captured"), None)
    existing = [r.refund_status for p in order.payments for r in p.refunds]
    return rules.check_refund(order.order_status, captured.payment_status if captured else None, existing), captured


async def check_refund_eligibility(customer_id: str, order_id: str) -> dict:
    async with get_sessionmaker()() as s:
        try:
            o = await get_owned_order(s, customer_id, order_id)
        except NotFoundError:
            return fail("order_not_found", f"No order {order_id} was found on this account.")
        r, pay = _evaluate(o)
        return ok({"order_id": o.order_id, "order_status": o.order_status, "eligible": r.eligible,
                   "reason_code": r.code, "reason": r.message,
                   "refund_amount": num(pay.amount) if pay and r.eligible else None})


async def revalidate_refund(session: AsyncSession, customer_id: str, params: dict) -> rules.RuleResult:
    o = await get_owned_order(session, customer_id, params["order_id"])
    return _evaluate(o)[0]


async def execute_refund_request(session: AsyncSession, customer_id: str, params: dict) -> dict:
    o = await get_owned_order(session, customer_id, params["order_id"])
    r, pay = _evaluate(o)
    if not r.eligible or pay is None:
        raise ValueError(r.message)
    ref = Refund(refund_id=await _next_refund_id(session), payment_pk=pay.id, order_pk=o.id, customer_pk=o.customer_pk,
                 refund_amount=pay.amount, currency=pay.currency, refund_status="requested",
                 reason="Refund requested via voice support", requested_at=utcnow(),
                 estimated_completion_date=rules.refund_estimated_completion(date.today()))
    session.add(ref)   # simulated record only; no real payment gateway is called
    return {"refund_id": ref.refund_id, "order_id": o.order_id, "amount": num(pay.amount),
            "status": "requested", "estimated_completion_date": iso(ref.estimated_completion_date)}
