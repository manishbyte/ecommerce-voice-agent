from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.orders import fetch_orders
from app.api.routes.payments import fetch_payments
from app.api.routes.refunds import fetch_refunds
from app.api.routes.tickets import fetch_tickets
from app.core.business_rules import OPEN_TICKET_STATUSES
from app.dependencies import get_session
from app.models import Customer, Order, SupportTicket
from app.schemas.customer import CustomerDetail, CustomerProfile, CustomerSummary

router = APIRouter(prefix="/customers", tags=["customers"])


async def _customer(db: AsyncSession, customer_id: str) -> Customer:
    c = (await db.execute(select(Customer).where(Customer.customer_id == customer_id))).scalar_one_or_none()
    if c is None:
        raise HTTPException(404, "Customer not found")
    return c


@router.get("", response_model=list[CustomerSummary])
async def list_customers(db: AsyncSession = Depends(get_session)):
    orders = select(func.count(Order.id)).where(Order.customer_pk == Customer.id).correlate(Customer).scalar_subquery()
    open_t = (select(func.count(SupportTicket.id)).where(SupportTicket.customer_pk == Customer.id,
                                                          SupportTicket.ticket_status.in_(OPEN_TICKET_STATUSES))
              .correlate(Customer).scalar_subquery())
    rows = (await db.execute(select(Customer, orders, open_t).order_by(Customer.customer_id))).all()
    return [CustomerSummary(customer_id=c.customer_id, full_name=c.full_name, mobile_number=c.mobile_number,
                            email=c.email, status=c.status, city=(c.address or {}).get("city"), total_orders=o or 0,
                            active_complaints=t or 0, preferred_language=c.preferred_language) for c, o, t in rows]


@router.get("/{customer_id}", response_model=CustomerDetail)
async def customer_detail(customer_id: str, db: AsyncSession = Depends(get_session)):
    c = await _customer(db, customer_id)
    return CustomerDetail(profile=CustomerProfile.model_validate(c), orders=await fetch_orders(db, customer_id),
                          payments=await fetch_payments(db, customer_id), refunds=await fetch_refunds(db, customer_id),
                          tickets=await fetch_tickets(db, customer_id))


@router.get("/{customer_id}/orders")
async def customer_orders(customer_id: str, db: AsyncSession = Depends(get_session)):
    await _customer(db, customer_id)
    return await fetch_orders(db, customer_id)


@router.get("/{customer_id}/payments")
async def customer_payments(customer_id: str, db: AsyncSession = Depends(get_session)):
    await _customer(db, customer_id)
    return await fetch_payments(db, customer_id)


@router.get("/{customer_id}/refunds")
async def customer_refunds(customer_id: str, db: AsyncSession = Depends(get_session)):
    await _customer(db, customer_id)
    return await fetch_refunds(db, customer_id)


@router.get("/{customer_id}/tickets")
async def customer_tickets(customer_id: str, db: AsyncSession = Depends(get_session)):
    await _customer(db, customer_id)
    return await fetch_tickets(db, customer_id)
