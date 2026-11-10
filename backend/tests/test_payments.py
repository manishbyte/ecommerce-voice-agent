import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Customer, Order, Payment
from app.tools import payment_tools


async def test_payment_status_scoped(db):
    res = await payment_tools.get_payment_status("CUS1003")
    assert res["ok"] and all(p["customer_id"] == "CUS1003" for p in res["data"])
    failed = [p for p in res["data"] if p["payment_status"] != "captured"]
    assert failed and "no amount was captured" in failed[0]["explanation"]


async def test_database_rejects_payment_for_someone_elses_order(db):
    async with db() as s:
        order = (await s.execute(select(Order).where(Order.order_id == "ORD1001"))).scalar_one()
        stranger = (await s.execute(select(Customer).where(Customer.id != order.customer_pk))).scalars().first()
        s.add(Payment(payment_id="PAY9999", order_pk=order.id, customer_pk=stranger.id, payment_method="upi",
                      transaction_reference=f"TXN{uuid.uuid4().hex[:8]}", amount=1, payment_status="captured"))
        with pytest.raises(IntegrityError):
            await s.commit()
