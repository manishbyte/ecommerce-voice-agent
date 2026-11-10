from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core import business_rules as rules
from app.models import Order, Payment, Refund
from app.tools import refund_tools


def test_refund_rules():
    assert rules.check_refund("cancelled", "captured", []).eligible
    assert not rules.check_refund("delivered", "captured", []).eligible
    assert rules.check_refund("cancelled", "failed", []).code == "no_captured_payment"
    assert rules.check_refund("cancelled", "captured", ["requested"]).code == "refund_exists"


def test_return_window_rules():
    d = date(2026, 11, 1)
    assert rules.check_return("delivered", d, date(2026, 11, 8), 10).eligible
    assert rules.check_return("delivered", d, date(2026, 11, 20), 10).code == "window_expired"
    assert rules.check_return("shipped", None, d, 10).code == "not_delivered"


async def test_refund_status_and_eligibility_tools(db):
    st = await refund_tools.get_refund_status("CUS1004")
    assert st["ok"] and st["data"][0]["refund_id"].startswith("REF")
    el = await refund_tools.check_refund_eligibility("CUS1003", "ORD1006")     # payment failed
    assert el["data"]["eligible"] is False and el["data"]["reason_code"] == "no_captured_payment"


async def test_database_rejects_refund_with_mismatched_order(db):
    async with db() as s:
        pay = (await s.execute(select(Payment))).scalars().first()
        other_order = (await s.execute(select(Order).where(Order.id != pay.order_pk))).scalars().first()
        s.add(Refund(refund_id="REF9999", payment_pk=pay.id, order_pk=other_order.id, customer_pk=pay.customer_pk,
                     refund_amount=1, refund_status="requested"))
        with pytest.raises(IntegrityError):
            await s.commit()
