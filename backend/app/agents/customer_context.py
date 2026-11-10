"""Customer Context Agent: establishes trusted customer context; identity fallback by mobile number."""
from __future__ import annotations

import re
import uuid

from sqlalchemy import update

from app.core.logging import emit_event
from app.database.connection import get_sessionmaker
from app.models import Conversation, Customer
from app.agents.state import AgentState, TurnTools
from app.core.security import normalize_mobile
from app.utils.formatting import normalize_digits

_WORD_DIGITS = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "शून्य": 0, "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5,
                "छह": 6, "छे": 6, "सात": 7, "आठ": 8, "नौ": 9}
_MOBILE_RE = re.compile(r"(?:\+?91[\s-]?)?[6-9](?:[\s-]?\d){9}")
MAX_IDENTITY_ATTEMPTS = 3


def extract_mobile(text: str) -> str | None:
    """Pull a 10-digit mobile out of digits or spoken digit words (English/Hindi)."""
    t = normalize_digits(text or "")
    m = _MOBILE_RE.search(t)
    if m:
        return normalize_mobile(m.group(0))
    words = re.split(r"[\s,.-]+", t.lower())
    digits = "".join(str(_WORD_DIGITS[w]) for w in words if w in _WORD_DIGITS)
    return digits[-10:] if len(digits) >= 10 else None


async def customer_context_node(state: AgentState) -> dict:
    """Load the verified customer's profile (customer id comes from the DB-bound conversation only)."""
    conv = state["conversation_id"]
    if not state.get("customer_verified"):
        await emit_event(conv, "customer_context", agent="customer_context", status="pending",
                         summary="Customer not yet verified")
        return {"customer_profile": {}}
    tools = TurnTools(state, "customer_context")
    prof = await tools("get_customer_profile")
    await emit_event(conv, "customer_context_loaded", agent="customer_context",
                     summary=f"Loaded context for {state.get('customer_id')}")
    return {"customer_profile": prof.get("data") or {}, "tool_execution_history": tools.records,
            "relevant_customer_context": {"customer_id": state.get("customer_id")}}


async def _bind_customer(conversation_id: str, customer_id: str) -> bool:
    """Bind a customer to an unbound conversation. Never re-binds an already-bound conversation."""
    from sqlalchemy import select

    async with get_sessionmaker()() as s:
        async with s.begin():
            cust = (await s.execute(select(Customer).where(Customer.customer_id == customer_id))).scalar_one_or_none()
            if cust is None:
                return False
            res = await s.execute(update(Conversation).where(Conversation.id == uuid.UUID(conversation_id),
                                                             Conversation.customer_pk.is_(None))
                                  .values(customer_pk=cust.id))
            return res.rowcount == 1


async def identity_node(state: AgentState) -> dict:
    """Mobile-number fallback verification. Discloses nothing until exactly one customer matches."""
    if state.get("customer_verified"):
        return {"identity_just_verified": False}
    conv = state["conversation_id"]
    attempts = state.get("identity_attempts", 0)
    msg = state.get("current_user_message", "")
    mobile = extract_mobile(msg)
    await emit_event(conv, "identity_verification", agent="customer_context", status="pending",
                     summary="Asking for registered mobile number" if not mobile else "Verifying mobile number")
    if attempts >= MAX_IDENTITY_ATTEMPTS:
        return {"notices": [{"type": "identity_failed", "locked": True}], "current_intent": "identity_verification"}
    if not mobile:
        return {"notices": [{"type": "ask_mobile"}], "current_intent": "identity_verification",
                "identity_just_verified": False}
    tools = TurnTools(state, "customer_context")
    res = await tools("find_customer_by_mobile", mobile=mobile)
    if res.get("ok") and await _bind_customer(conv, res["data"]["customer_id"]):
        cid = res["data"]["customer_id"]
        state2 = {**state, "customer_id": cid, "customer_verified": True}
        prof = await TurnTools(state2, "customer_context")("get_customer_profile")
        await emit_event(conv, "customer_verified", agent="customer_context", summary=f"Verified customer {cid}")
        return {"customer_id": cid, "customer_verified": True, "customer_profile": prof.get("data") or {},
                "identity_just_verified": True, "current_intent": "identity_verification",
                "notices": [{"type": "identity_verified"}], "tool_execution_history": tools.records}
    await emit_event(conv, "identity_failed", agent="customer_context", status="error", summary="Mobile could not be verified")
    return {"identity_attempts": attempts + 1, "notices": [{"type": "identity_failed"}],
            "current_intent": "identity_verification", "tool_execution_history": tools.records}
