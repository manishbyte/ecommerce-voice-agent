from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.dependencies import get_session
from app.models import Customer, Payment
from app.schemas.payment import payment_out

router = APIRouter(prefix="/payments", tags=["payments"])


def payments_query(customer_id: str):
    return (select(Payment).join(Customer, Customer.id == Payment.customer_pk).where(Customer.customer_id == customer_id)
            .options(joinedload(Payment.order)).order_by(Payment.payment_id))


async def fetch_payments(db: AsyncSession, customer_id: str) -> list[dict]:
    return [payment_out(p, p.order.order_id, customer_id) for p in (await db.execute(payments_query(customer_id))).scalars().all()]


@router.get("/{payment_id}")
async def get_payment(payment_id: str, customer_id: str = Query(...), db: AsyncSession = Depends(get_session)) -> dict:
    p = (await db.execute(payments_query(customer_id).where(Payment.payment_id == payment_id))).scalars().first()
    if p is None:
        raise HTTPException(404, "Payment not found for this customer")
    return payment_out(p, p.order.order_id, customer_id)
