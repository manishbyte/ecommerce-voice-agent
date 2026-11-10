from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.dependencies import get_session
from app.models import Customer, Refund
from app.schemas.refund import refund_out

router = APIRouter(prefix="/refunds", tags=["refunds"])


def refunds_query(customer_id: str):
    return (select(Refund).join(Customer, Customer.id == Refund.customer_pk).where(Customer.customer_id == customer_id)
            .options(joinedload(Refund.order), joinedload(Refund.payment)).order_by(Refund.refund_id))


async def fetch_refunds(db: AsyncSession, customer_id: str) -> list[dict]:
    rows = (await db.execute(refunds_query(customer_id))).scalars().all()
    return [refund_out(r, r.order.order_id, r.payment.payment_id, customer_id) for r in rows]


@router.get("/{refund_id}")
async def get_refund(refund_id: str, customer_id: str = Query(...), db: AsyncSession = Depends(get_session)) -> dict:
    r = (await db.execute(refunds_query(customer_id).where(Refund.refund_id == refund_id))).scalars().first()
    if r is None:
        raise HTTPException(404, "Refund not found for this customer")
    return refund_out(r, r.order.order_id, r.payment.payment_id, customer_id)
