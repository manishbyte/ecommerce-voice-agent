from __future__ import annotations

from sqlalchemy import or_, select

from app.database.connection import get_sessionmaker
from app.models import Product
from app.schemas.product import ProductOut
from app.tools import fail, ok
from app.tools.order_tools import tokens
from app.utils.identifiers import PRODUCT_ID_RE


async def get_product_details(query: str | None = None, product_id: str | None = None, limit: int = 3) -> dict:
    """Public catalogue lookup (not customer data)."""
    async with get_sessionmaker()() as s:
        if product_id:
            if not PRODUCT_ID_RE.match(product_id):
                return fail("invalid_product_id", "Product IDs look like PRD1001.")
            rows = (await s.execute(select(Product).where(Product.product_id == product_id))).scalars().all()
        else:
            toks = tokens(query or "")
            if not toks:
                return fail("empty_query", "Which product are you asking about?")
            conds = [or_(Product.name.ilike(f"%{t}%"), Product.category.ilike(f"%{t}%"), Product.brand.ilike(f"%{t}%"))
                     for t in toks]
            cand = (await s.execute(select(Product).where(or_(*conds)))).scalars().all()
            scored = sorted(((sum(1 for t in toks if t in f"{p.name} {p.category} {p.brand}".lower()), p) for p in cand),
                            key=lambda x: -x[0])
            rows = [p for _, p in scored][:limit]
        if not rows:
            return fail("product_not_found", "No matching product was found in the catalogue.")
        return ok([ProductOut.from_model(p).model_dump() for p in rows], count=len(rows))


async def check_product_availability(query: str | None = None, product_id: str | None = None) -> dict:
    res = await get_product_details(query=query, product_id=product_id, limit=3)
    if not res["ok"]:
        return res
    return ok([{"product_id": p["product_id"], "name": p["name"], "in_stock": p["stock_quantity"] > 0 and p["is_active"],
                "stock_quantity": p["stock_quantity"], "unit_price": p["unit_price"]} for p in res["data"]])
