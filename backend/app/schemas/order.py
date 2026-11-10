from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.core.business_rules import ORDER_STATUSES
from app.utils.formatting import iso, num


class OrderItemSeed(BaseModel):
    order_item_id: str
    order_id: str
    product_id: str
    quantity: int = Field(gt=0)
    unit_price: Decimal
    line_total: Decimal


class OrderSeed(BaseModel):
    order_id: str
    customer_id: str
    order_date: date
    order_status: str
    subtotal: Decimal
    shipping_fee: Decimal = Decimal(0)
    discount_amount: Decimal = Decimal(0)
    total_amount: Decimal
    currency: str = "INR"
    shipping_address: dict
    estimated_delivery_date: date | None = None
    delivered_at: date | None = None
    tracking_number: str | None = None
    carrier: str | None = None
    scenario_note: str | None = None

    def model_post_init(self, _ctx) -> None:
        if self.order_status not in ORDER_STATUSES:
            raise ValueError(f"unknown order_status {self.order_status} on {self.order_id}")


def item_out(i) -> dict:
    return {"order_item_id": i.order_item_id, "product_id": i.product.product_id, "product_name": i.product.name,
            "quantity": i.quantity, "unit_price": num(i.unit_price), "line_total": num(i.line_total)}


def order_out(o) -> dict:
    """Serialise an Order. Requires `customer`, `items.product` to be loaded."""
    return {
        "order_id": o.order_id, "customer_id": o.customer.customer_id, "order_date": iso(o.order_date),
        "order_status": o.order_status, "subtotal": num(o.subtotal), "shipping_fee": num(o.shipping_fee),
        "discount_amount": num(o.discount_amount), "total_amount": num(o.total_amount), "currency": o.currency,
        "shipping_address": o.shipping_address, "estimated_delivery_date": iso(o.estimated_delivery_date),
        "delivered_at": iso(o.delivered_at), "tracking_number": o.tracking_number, "carrier": o.carrier,
        "items": [item_out(i) for i in o.items],
    }
