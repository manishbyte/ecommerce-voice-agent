"""Idempotent seeding of the demo dataset from the root-level data/customers.json.

* Validates the entire file with Pydantic (including cross-record integrity).
* Inserts only business ids that do not already exist -> safe to run on every startup.
* Never deletes or overwrites existing rows.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, PrivateAttr, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Customer, Order, OrderItem, Payment, Product, Refund, SupportTicket
from app.schemas.customer import CustomerSeed
from app.schemas.order import OrderItemSeed, OrderSeed
from app.schemas.payment import PaymentSeed
from app.schemas.product import ProductSeed
from app.schemas.refund import RefundSeed
from app.schemas.ticket import TicketSeed

log = logging.getLogger(__name__)


class SeedDataset(BaseModel):
    dataset_version: str | None = None
    description: str | None = None
    currency: str | None = None
    customers: list[CustomerSeed]
    products: list[ProductSeed]
    orders: list[OrderSeed]
    order_items: list[OrderItemSeed]
    payments: list[PaymentSeed]
    refunds: list[RefundSeed]
    support_tickets: list[TicketSeed]

    _ticket_fixes: list[str] = PrivateAttr(default_factory=list)

    @property
    def ticket_fixes(self) -> list[str]:
        return self._ticket_fixes

    @model_validator(mode="after")
    def _check_integrity(self) -> "SeedDataset":
        def unique(label: str, values: list[str]) -> None:
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {label} in seed file")

        unique("customer_id", [c.customer_id for c in self.customers])
        unique("mobile_number", [c.mobile_number for c in self.customers])
        unique("product_id", [p.product_id for p in self.products])
        unique("order_id", [o.order_id for o in self.orders])
        unique("order_item_id", [i.order_item_id for i in self.order_items])
        unique("payment_id", [p.payment_id for p in self.payments])
        unique("refund_id", [r.refund_id for r in self.refunds])
        unique("ticket_id", [t.ticket_id for t in self.support_tickets])

        customers = {c.customer_id for c in self.customers}
        products = {p.product_id for p in self.products}
        orders = {o.order_id: o for o in self.orders}
        payments = {p.payment_id: p for p in self.payments}

        for o in self.orders:
            if o.customer_id not in customers:
                raise ValueError(f"order {o.order_id} -> unknown customer {o.customer_id}")
        lines: dict[str, Decimal] = {}
        for i in self.order_items:
            if i.order_id not in orders or i.product_id not in products:
                raise ValueError(f"order item {i.order_item_id} has a dangling reference")
            if i.quantity * i.unit_price != i.line_total:
                raise ValueError(f"order item {i.order_item_id}: quantity*unit_price != line_total")
            lines[i.order_id] = lines.get(i.order_id, Decimal(0)) + i.line_total
        for o in self.orders:
            if lines.get(o.order_id, Decimal(0)) != o.subtotal:
                raise ValueError(f"order {o.order_id}: subtotal does not match its items")
            if o.subtotal + o.shipping_fee - o.discount_amount != o.total_amount:
                raise ValueError(f"order {o.order_id}: total_amount arithmetic is inconsistent")
        for p in self.payments:
            o = orders.get(p.order_id)
            if o is None or o.customer_id != p.customer_id:
                raise ValueError(f"payment {p.payment_id} does not belong to the customer who owns {p.order_id}")
        for r in self.refunds:
            o, p = orders.get(r.order_id), payments.get(r.payment_id)
            if o is None or o.customer_id != r.customer_id or p is None or p.order_id != r.order_id:
                raise ValueError(f"refund {r.refund_id} has inconsistent order/payment/customer references")

        # Tickets: the order is the source of truth. A ticket whose customer_id disagrees with the
        # owner of its order is re-assigned to the owner (and logged) so the schema's composite FK holds.
        for t in self.support_tickets:
            if t.customer_id not in customers:
                raise ValueError(f"ticket {t.ticket_id} -> unknown customer {t.customer_id}")
            if t.order_id is None:
                continue
            o = orders.get(t.order_id)
            if o is None:
                raise ValueError(f"ticket {t.ticket_id} -> unknown order {t.order_id}")
            if o.customer_id != t.customer_id:
                self._ticket_fixes.append(
                    f"{t.ticket_id}: customer {t.customer_id} -> {o.customer_id} (owner of {t.order_id})")
                t.customer_id = o.customer_id
        return self


def load_dataset(path: Path) -> SeedDataset:
    if not path.is_file():
        raise FileNotFoundError(f"Seed file not found: {path}")
    return SeedDataset.model_validate(json.loads(path.read_text(encoding="utf-8")))


async def _existing(session: AsyncSession, model, business_col) -> dict[str, object]:
    rows = (await session.execute(select(business_col, model.id))).all()
    return {r[0]: r[1] for r in rows}


async def seed_database(factory: async_sessionmaker[AsyncSession], path: Path) -> dict[str, int]:
    ds = load_dataset(path)
    for fix in ds.ticket_fixes:
        log.warning("seed data repaired: ticket %s", fix)
    inserted: dict[str, int] = {}

    async with factory() as session:
        async with session.begin():
            cust = await _existing(session, Customer, Customer.customer_id)
            new = [c for c in ds.customers if c.customer_id not in cust]
            for c in new:
                row = Customer(customer_id=c.customer_id, full_name=c.full_name, email=c.email,
                               mobile_number=c.mobile_number, date_of_birth=c.date_of_birth, status=c.status,
                               address=c.address.model_dump(), preferred_language=c.preferred_language,
                               created_at=c.created_at)
                session.add(row)
                cust[c.customer_id] = None  # filled after flush
            await session.flush()
            cust = await _existing(session, Customer, Customer.customer_id)
            inserted["customers"] = len(new)

            prod = await _existing(session, Product, Product.product_id)
            new_p = [p for p in ds.products if p.product_id not in prod]
            session.add_all([Product(**p.model_dump()) for p in new_p])
            await session.flush()
            prod = await _existing(session, Product, Product.product_id)
            inserted["products"] = len(new_p)

            orders = await _existing(session, Order, Order.order_id)
            new_o = [o for o in ds.orders if o.order_id not in orders]
            for o in new_o:
                d = o.model_dump(exclude={"customer_id", "order_id"})
                session.add(Order(order_id=o.order_id, customer_pk=cust[o.customer_id], **d))
            await session.flush()
            orders = await _existing(session, Order, Order.order_id)
            inserted["orders"] = len(new_o)

            items = await _existing(session, OrderItem, OrderItem.order_item_id)
            new_i = [i for i in ds.order_items if i.order_item_id not in items]
            for i in new_i:
                session.add(OrderItem(order_item_id=i.order_item_id, order_pk=orders[i.order_id],
                                      product_pk=prod[i.product_id], quantity=i.quantity,
                                      unit_price=i.unit_price, line_total=i.line_total))
            inserted["order_items"] = len(new_i)

            pays = await _existing(session, Payment, Payment.payment_id)
            new_pay = [p for p in ds.payments if p.payment_id not in pays]
            for p in new_pay:
                session.add(Payment(payment_id=p.payment_id, order_pk=orders[p.order_id],
                                    customer_pk=cust[p.customer_id], payment_method=p.payment_method,
                                    transaction_reference=p.transaction_reference, amount=p.amount,
                                    currency=p.currency, payment_status=p.payment_status, paid_at=p.paid_at))
            await session.flush()
            pays = await _existing(session, Payment, Payment.payment_id)
            inserted["payments"] = len(new_pay)

            refs = await _existing(session, Refund, Refund.refund_id)
            new_r = [r for r in ds.refunds if r.refund_id not in refs]
            for r in new_r:
                session.add(Refund(refund_id=r.refund_id, payment_pk=pays[r.payment_id], order_pk=orders[r.order_id],
                                   customer_pk=cust[r.customer_id], refund_amount=r.refund_amount,
                                   currency=r.currency, refund_status=r.refund_status, reason=r.reason,
                                   requested_at=r.requested_at, processed_at=r.processed_at,
                                   estimated_completion_date=r.estimated_completion_date))
            inserted["refunds"] = len(new_r)

            tks = await _existing(session, SupportTicket, SupportTicket.ticket_id)
            new_t = [t for t in ds.support_tickets if t.ticket_id not in tks]
            for t in new_t:
                session.add(SupportTicket(ticket_id=t.ticket_id, customer_pk=cust[t.customer_id],
                                          order_pk=orders[t.order_id] if t.order_id else None,
                                          category=t.category, subject=t.subject, description=t.description,
                                          ticket_status=t.ticket_status, priority=t.priority, source="seed",
                                          created_at=t.created_at, updated_at=t.updated_at,
                                          resolution=t.resolution))
            inserted["support_tickets"] = len(new_t)
    log.info("Seed complete: %s", inserted)
    return inserted
