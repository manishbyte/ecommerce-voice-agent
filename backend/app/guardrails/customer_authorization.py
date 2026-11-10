"""Customer ownership / data-isolation enforcement (business-data authorization, not login)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from app.core.exceptions import NotFoundError, UnauthorizedAccessError
from app.models import Customer, Order, OrderItem, Payment
from app.utils.identifiers import find_ids


async def resolve_customer(session: AsyncSession, customer_id: str | None) -> Customer:
    if not customer_id:
        raise NotFoundError("customer not found")
    row = (await session.execute(select(Customer).where(Customer.customer_id == customer_id))).scalar_one_or_none()
    if row is None:
        raise NotFoundError("customer not found")
    return row


def _order_query(order_id: str, customer_id: str):
    return (select(Order).join(Customer, Customer.id == Order.customer_pk)
            .where(Order.order_id == order_id, Customer.customer_id == customer_id)
            .options(joinedload(Order.customer),
                     selectinload(Order.items).joinedload(OrderItem.product),
                     selectinload(Order.payments).selectinload(Payment.refunds)))


async def get_owned_order(session: AsyncSession, customer_id: str, order_id: str) -> Order:
    """Return the order only if it belongs to `customer_id`.

    A missing order and someone else's order are indistinguishable to the caller.
    """
    order = (await session.execute(_order_query(order_id, customer_id))).scalar_one_or_none()
    if order is None:
        raise UnauthorizedAccessError(f"order {order_id} not found for this customer")
    return order


def find_foreign_identifiers(text: str, customer_id: str | None, owned_order_ids: set[str] | None = None) -> dict:
    """Identifiers in the message that point at a different customer (CUS) - used pre-tool as a signal."""
    foreign_customers = [c for c in find_ids(text, "CUS") if c != customer_id]
    return {"foreign_customers": foreign_customers}
