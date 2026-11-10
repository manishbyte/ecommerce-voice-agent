from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from app.utils.formatting import num


class ProductSeed(BaseModel):
    product_id: str
    name: str
    category: str
    brand: str | None = None
    description: str | None = None
    unit_price: Decimal = Field(ge=0)
    currency: str = "INR"
    stock_quantity: int = Field(ge=0)
    warranty_period: str | None = None
    is_active: bool = True


class ProductOut(BaseModel):
    product_id: str
    name: str
    category: str
    brand: str | None
    description: str | None
    unit_price: float | int
    currency: str
    stock_quantity: int
    warranty_period: str | None
    is_active: bool

    @classmethod
    def from_model(cls, p) -> "ProductOut":
        return cls(product_id=p.product_id, name=p.name, category=p.category, brand=p.brand,
                   description=p.description, unit_price=num(p.unit_price), currency=p.currency,
                   stock_quantity=p.stock_quantity, warranty_period=p.warranty_period, is_active=p.is_active)
