from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.business_rules import explain_payment
from app.database.connection import get_sessionmaker
from app.models import Customer, Order, Payment
from app.schemas.payment import payment_out
from app.tools import fail, ok


async def get_payment_status(customer_id: str, order_id: str | None = None, limit: int = 20) -> dict:
    async with get_sessionmaker()() as s:
        q = (select(Payment).join(Customer, Customer.id == Payment.customer_pk)
             .join(Order, Order.id == Payment.order_pk)
             .where(Customer.customer_id == customer_id)
             .options(joinedload(Payment.order)).order_by(Payment.payment_id.desc()).limit(limit))
        if order_id:
            q = q.where(Order.order_id == order_id)
        rows = (await s.execute(q)).scalars().all()
        if not rows:
            return fail("payment_not_found", "No payment records were found for that request.")
        out = []
        for p in rows:
            d = payment_out(p, p.order.order_id, customer_id)
            d["order_status"] = p.order.order_status
            d["explanation"] = explain_payment(p.payment_status, p.order.order_status)
            out.append(d)
        return ok(out, count=len(out))


async def get_payment_history(customer_id: str, limit: int = 10) -> dict:
    return await get_payment_status(customer_id, None, limit)
