"""Profile / address editing, change log, customer management and the confirmed voice-agent edit flow."""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.agents.graph import run_turn, summarize_turn
from app.api.router import api_router
from app.core import validators as v
from app.models import ChangeLog, Customer, Order


@pytest.fixture
async def api(db):
    app = FastAPI()
    app.include_router(api_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


# ---------------------------------------------------------------- validators (pure)
@pytest.mark.parametrize("fn,good,bad", [
    (v.validate_email, "a.b@example.com", "a@b"), (v.validate_mobile, "98765 43210", "12345"),
    (v.validate_pin, "411001", "41100"), (v.validate_name, "Aarav Sharma", "A1"), (v.validate_language, "Hindi", "klingon")])
def test_validators(fn, good, bad):
    assert fn(good)[1] is None and fn(bad)[0] is None


def test_mobile_normalised_and_pin_rules():
    assert v.validate_mobile("+91-98765 43210")[0] == "+919876543210"
    assert v.validate_mobile("5876543210")[0] is None            # must start 6-9
    assert v.validate_pin("011001")[0] is None


def test_profile_changes_reject_protected_fields():
    clean, errors = v.validate_profile_changes({"email": "x@y.com", "status": "vip", "customer_id": "CUS9"})
    assert clean == {"email": "x@y.com"} and {"status", "customer_id"} <= set(errors)


def test_text_parser_extracts_values():
    assert v.parse_profile_changes("change my email to a.b@gmail.com")["email"] == "a.b@gmail.com"
    addr = v.parse_profile_changes("change my address to 12 MG Road, Pune, Maharashtra 411001")["address"]
    assert addr == {"postal_code": "411001", "line1": "12 MG Road", "city": "Pune", "state": "Maharashtra"}


# ---------------------------------------------------------------- dashboard API
async def test_edit_profile_validates_logs_and_checks_uniqueness(api, db):
    r = await api.patch("/api/customers/CUS1001", json={"email": "aarav.new@example.com", "address": {"city": "Mumbai", "postal_code": "400001"}})
    assert r.status_code == 200 and r.json()["email"] == "aarav.new@example.com" and r.json()["address"]["city"] == "Mumbai"
    async with db() as s:
        rows = (await s.execute(select(ChangeLog).where(ChangeLog.customer_id == "CUS1001"))).scalars().all()
    assert {x.field for x in rows} == {"email", "address"} and all(x.source == "dashboard" and x.old_value for x in rows)
    assert (await api.patch("/api/customers/CUS1001", json={"mobile_number": "12345"})).status_code == 422
    assert (await api.patch("/api/customers/CUS1001", json={"address": {"postal_code": "41"}})).status_code == 422
    other = (await api.get("/api/customers/CUS1002")).json()["profile"]["email"]
    assert (await api.patch("/api/customers/CUS1001", json={"email": other})).status_code == 409      # already used


async def test_order_address_only_before_dispatch(api):
    addr = {"address": {"line1": "12 MG Road", "city": "Pune", "state": "Maharashtra", "postal_code": "411001"}}
    ok = await api.patch("/api/orders/ORD1010/address", params={"customer_id": "CUS1005"}, json=addr)
    assert ok.status_code == 200 and ok.json()["order"]["shipping_address"]["postal_code"] == "411001"      # processing
    shipped = await api.patch("/api/orders/ORD1002/address", params={"customer_id": "CUS1001"}, json=addr)
    assert shipped.status_code == 409 and "before dispatch" in shipped.json()["detail"]
    foreign = await api.patch("/api/orders/ORD1003/address", params={"customer_id": "CUS1001"}, json=addr)
    assert foreign.status_code == 404                                                                       # not their order


async def test_create_deactivate_activate_delete(api, db):
    body = {"full_name": "Test User", "email": "test.user@example.com", "mobile_number": "9000000001",
            "address": {"line1": "1 Test Street", "city": "Pune", "state": "Maharashtra", "postal_code": "411001"}}
    r = await api.post("/api/customers", json=body)
    assert r.status_code == 201 and r.json()["customer_id"] == "CUS1016" and r.json()["mobile_number"] == "+919000000001"
    assert (await api.post("/api/customers", json=body)).status_code == 409                                  # duplicate email/mobile
    assert (await api.post("/api/customers", json={**body, "email": "bad"})).status_code == 422
    assert (await api.post("/api/customers/CUS1016/deactivate")).json()["status"] == "inactive"
    blocked = await api.post("/api/conversations", json={"customer_id": "CUS1016"})
    assert blocked.status_code == 409                                                                       # deactivated: no new calls
    assert (await api.post("/api/customers/CUS1016/activate")).json()["status"] == "active"
    assert (await api.post("/api/conversations", json={"customer_id": "CUS1016"})).status_code == 201
    assert (await api.delete("/api/customers/CUS1016")).json()["deleted"] is True
    assert (await api.get("/api/customers/CUS1016")).status_code == 404
    assert (await api.delete("/api/customers/CUS1001")).status_code == 409                                  # seeded customers are protected
    log = (await api.get("/api/changes", params={"customer_id": "CUS1016"})).json()
    assert {x["field"] for x in log} >= {"__created__", "status", "__deleted__"}


async def test_demo_generator_creates_consistent_testable_data(api, db):
    r = await api.post("/api/customers/demo", json={"count": 4, "with_orders": True})
    assert r.status_code == 200 and r.json()["count"] == 4
    ids = [c["customer_id"] for c in r.json()["created"]]
    for cid in ids:
        d = (await api.get(f"/api/customers/{cid}")).json()
        assert d["orders"] and d["payments"]
        assert any(o["order_status"] == "processing" for o in d["orders"])           # at least one editable/cancellable order
        for o in d["orders"]:
            assert o["total_amount"] == sum(i["line_total"] for i in o["items"])
    assert len({c["mobile_number"] for c in r.json()["created"]}) == 4
    assert (await api.delete(f"/api/customers/{ids[0]}")).status_code == 200


# ---------------------------------------------------------------- voice agent: confirmed edits
async def say(graph, cid, text):
    return summarize_turn(await run_turn(graph, cid, text))


async def test_voice_profile_edit_needs_confirmation_and_is_logged(graph, make_conversation, db):
    cid = await make_conversation("CUS1001")
    await say(graph, cid, None); await say(graph, cid, "English")
    ask = await say(graph, cid, "I want to change my email")
    assert ask["pending_action"] is None and "email" in ask["response"].lower()           # asks for the new value first
    prop = await say(graph, cid, "change my email to aarav.new@example.com")
    assert prop["pending_action"]["action_type"] == "update_profile" and "aarav.new@example.com" in prop["response"]
    async with db() as s:                                                                  # nothing saved yet
        assert (await s.execute(select(Customer.email).where(Customer.customer_id == "CUS1001"))).scalar_one() != "aarav.new@example.com"
    done = await say(graph, cid, "yes")
    assert done["action_status"] == "executed"
    async with db() as s:
        assert (await s.execute(select(Customer.email).where(Customer.customer_id == "CUS1001"))).scalar_one() == "aarav.new@example.com"
        log = (await s.execute(select(ChangeLog).where(ChangeLog.source == "voice_agent"))).scalars().all()
    assert log and log[0].field == "email" and log[0].conversation_id == cid


async def test_voice_invalid_values_are_rejected_not_proposed(graph, make_conversation):
    cid = await make_conversation("CUS1001")
    await say(graph, cid, None); await say(graph, cid, "English")
    bad = await say(graph, cid, "change my mobile number to 12345")
    assert bad["pending_action"] is None and "10" in bad["response"]


async def test_voice_order_address_flow_and_dispatch_rule(graph, make_conversation, db):
    cid = await make_conversation("CUS1005")
    await say(graph, cid, None); await say(graph, cid, "English")
    ask = await say(graph, cid, "I want to change the delivery address for ORD1010")
    assert ask["pending_action"] is None and "address" in ask["response"].lower()
    prop = await say(graph, cid, "12 MG Road, Pune, Maharashtra 411001")                # follow-up turn answers the question
    assert prop["pending_action"]["action_type"] == "update_order_address" and "411001" in prop["response"]
    assert (await say(graph, cid, "yes"))["action_status"] == "executed"
    async with db() as s:
        addr = (await s.execute(select(Order.shipping_address).where(Order.order_id == "ORD1010"))).scalar_one()
    assert addr["postal_code"] == "411001" and addr["city"] == "Pune"
    cid2 = await make_conversation("CUS1001")
    await say(graph, cid2, None); await say(graph, cid2, "English")
    late = await say(graph, cid2, "change the delivery address of ORD1002 to 5 Park Street, Pune, Maharashtra 411002")
    assert late["pending_action"] is None and "before dispatch" in late["response"]


async def test_voice_cannot_edit_someone_elses_details(graph, make_conversation):
    cid = await make_conversation("CUS1001")
    await say(graph, cid, None); await say(graph, cid, "English")
    r = await say(graph, cid, "Change the email of customer CUS1002 to attacker@example.com")
    assert r["pending_action"] is None and "attacker@example.com" not in (r["response"] or "")
    r2 = await say(graph, cid, "change the delivery address of ORD1003 to 1 Hacker Lane, Pune, Maharashtra 411001")
    assert r2["pending_action"] is None
