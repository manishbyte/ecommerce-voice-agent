from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.dependencies import get_session
from app.models import Customer, Order, OrderItem
from app.schemas.order import order_out

router = APIRouter(prefix="/orders", tags=["orders"])


def orders_query(customer_id: str):
    return (select(Order).join(Customer, Customer.id == Order.customer_pk).where(Customer.customer_id == customer_id)
            .options(joinedload(Order.customer), selectinload(Order.items).joinedload(OrderItem.product))
            .order_by(Order.order_date.desc(), Order.order_id.desc()))


async def fetch_orders(db: AsyncSession, customer_id: str) -> list[dict]:
    return [order_out(o) for o in (await db.execute(orders_query(customer_id))).scalars().all()]


@router.get("/{order_id}")
async def get_order(order_id: str, customer_id: str = Query(..., description="Scopes the lookup to this customer"),
                    db: AsyncSession = Depends(get_session)) -> dict:
    o = (await db.execute(orders_query(customer_id).where(Order.order_id == order_id))).scalars().first()
    if o is None:
        raise HTTPException(404, "Order not found for this customer")
    return order_out(o)
