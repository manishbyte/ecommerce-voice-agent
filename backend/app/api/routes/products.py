from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_session
from app.models import Product
from app.schemas.product import ProductOut

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductOut])
async def list_products(db: AsyncSession = Depends(get_session)):
    rows = (await db.execute(select(Product).order_by(Product.product_id))).scalars().all()
    return [ProductOut.from_model(p) for p in rows]
