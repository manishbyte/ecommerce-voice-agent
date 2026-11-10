from __future__ import annotations

from sqlalchemy import select

from app.core.security import mask_mobile, normalize_mobile
from app.database.connection import get_sessionmaker
from app.guardrails.customer_authorization import resolve_customer
from app.models import Customer
from app.tools import fail, ok


async def get_customer_profile(customer_id: str) -> dict:
    async with get_sessionmaker()() as s:
        c = await resolve_customer(s, customer_id)
        a = c.address or {}
        return ok({"customer_id": c.customer_id, "full_name": c.full_name, "first_name": c.full_name.split()[0],
                   "email": c.email, "mobile_masked": mask_mobile(c.mobile_number), "status": c.status,
                   "city": a.get("city"), "state": a.get("state"), "preferred_language": c.preferred_language})


async def find_customer_by_mobile(mobile: str) -> dict:
    """Identity fallback: succeeds only when exactly one customer matches the number."""
    last10 = normalize_mobile(mobile)
    if not last10:
        return fail("invalid_mobile", "That doesn't look like a 10-digit mobile number.")
    async with get_sessionmaker()() as s:
        rows = (await s.execute(select(Customer).where(Customer.mobile_number.like(f"%{last10}")))).scalars().all()
        if len(rows) != 1:
            return fail("no_unique_match", "No unique customer matches that number.")
        return ok({"customer_id": rows[0].customer_id})
