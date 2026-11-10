from app.guardrails.tool_validation import run_tool
from app.tools import order_tools


def _state(cid="CUS1001", verified=True):
    return {"conversation_id": None, "customer_id": cid, "customer_verified": verified}


async def test_orders_belong_to_customer(db):
    res = await order_tools.get_customer_orders("CUS1001")
    assert res["ok"] and res["count"] >= 1
    assert all(o["customer_id"] == "CUS1001" for o in res["data"])


async def test_missing_and_foreign_orders_look_identical(db):
    foreign = (await order_tools.get_customer_orders("CUS1002"))["data"][0]["order_id"]
    a = await order_tools.get_order_details("CUS1001", foreign)
    b = await order_tools.get_order_details("CUS1001", "ORD9999")
    assert not a["ok"] and not b["ok"] and a["error"] == b["error"] == "order_not_found"
    assert "CUS1002" not in str(a)


async def test_tool_gateway_blocks_unsafe_calls(db):
    r, rec = await run_tool(_state(), "drop_table", name="customers")
    assert r["error"] == "tool_not_allowed" and not rec["ok"]
    r, _ = await run_tool(_state(), "get_order_details", order_id="x'; DROP TABLE orders;--")
    assert r["error"] == "invalid_arguments"
    r, _ = await run_tool(_state(), "get_order_details", order_id="ORD1001", customer_id="CUS1002")   # cannot choose customer
    assert r["error"] == "invalid_arguments"
    r, _ = await run_tool(_state(verified=False), "get_customer_orders")
    assert r["error"] == "customer_not_verified"


async def test_cancellation_rules(db):
    ok = await order_tools.check_cancellation_eligibility("CUS1005", "ORD1010")
    assert ok["data"]["eligible"] is True                     # processing
    no = await order_tools.check_cancellation_eligibility("CUS1001", "ORD1002")
    assert no["data"]["eligible"] is False                    # shipped
