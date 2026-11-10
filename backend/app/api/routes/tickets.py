from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.dependencies import get_session
from app.models import Customer, SupportTicket
from app.schemas.ticket import ticket_out

router = APIRouter(prefix="/tickets", tags=["tickets"])


def tickets_query(customer_id: str):
    return (select(SupportTicket).join(Customer, Customer.id == SupportTicket.customer_pk)
            .where(Customer.customer_id == customer_id).options(joinedload(SupportTicket.order))
            .order_by(SupportTicket.created_at.desc()))


async def fetch_tickets(db: AsyncSession, customer_id: str) -> list[dict]:
    rows = (await db.execute(tickets_query(customer_id))).scalars().all()
    return [ticket_out(t, t.order.order_id if t.order else None, customer_id) for t in rows]


@router.get("")
async def list_tickets(customer_id: str = Query(...), db: AsyncSession = Depends(get_session)) -> list[dict]:
    return await fetch_tickets(db, customer_id)
