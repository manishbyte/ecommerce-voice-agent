import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.router import api_router
from app.config import get_settings
from app.database.seed import SeedDataset, load_dataset, seed_database
from app.models import Customer, Order, Payment, Product, Refund, SupportTicket


def test_seed_file_validates_and_has_15_customers():
    ds = load_dataset(get_settings().seed_file)
    assert len(ds.customers) == 15 and ds.products and ds.orders


def test_invalid_seed_data_is_rejected():
    raw = json.loads(get_settings().seed_file.read_text(encoding="utf-8"))
    raw["orders"][0]["customer_id"] = "CUS9999"
    with pytest.raises(Exception):
        SeedDataset.model_validate(raw)
    raw = json.loads(get_settings().seed_file.read_text(encoding="utf-8"))
    raw["payments"][0]["customer_id"] = "CUS1015" if raw["payments"][0]["customer_id"] != "CUS1015" else "CUS1001"
    with pytest.raises(Exception):
        SeedDataset.model_validate(raw)


def test_ticket_ownership_is_repaired_to_the_order_owner():
    ds = load_dataset(get_settings().seed_file)
    owners = {o.order_id: o.customer_id for o in ds.orders}
    assert all(owners[t.order_id] == t.customer_id for t in ds.support_tickets if t.order_id)
    assert ds.ticket_fixes  # the shipped file contains mismatched tickets that must be reported


async def test_seed_is_idempotent(db):
    again = await seed_database(db, get_settings().seed_file)
    assert all(v == 0 for v in again.values())
    async with db() as s:
        counts = {m.__tablename__: (await s.execute(select(func.count()).select_from(m))).scalar_one()
                  for m in (Customer, Product, Order, Payment, Refund, SupportTicket)}
    assert counts["customers"] == 15 and counts["support_tickets"] == 20


async def test_customer_api(db):
    app = FastAPI()
    app.include_router(api_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        lst = (await c.get("/api/customers")).json()
        assert len(lst) == 15 and {"total_orders", "active_complaints"} <= set(lst[0])
        d = (await c.get("/api/customers/CUS1001")).json()
        assert d["profile"]["customer_id"] == "CUS1001"
        assert all(o["customer_id"] == "CUS1001" for o in d["orders"])
        assert (await c.get("/api/customers/CUS9999")).status_code == 404
        # scoped lookups: another customer's order is indistinguishable from a missing one
        other = next(o for o in (await c.get("/api/customers/CUS1002/orders")).json())["order_id"]
        assert (await c.get(f"/api/orders/{other}", params={"customer_id": "CUS1001"})).status_code == 404
        assert (await c.get(f"/api/orders/{other}", params={"customer_id": "CUS1002"})).status_code == 200
