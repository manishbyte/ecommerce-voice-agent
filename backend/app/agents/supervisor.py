"""Supervisor Agent: intent classification and routing plan. Never performs actions itself."""
from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.prompts import SUPERVISOR_SYSTEM
from app.agents.routing import INTENTS, plan_agents
from app.agents.state import AgentState
from app.core.logging import emit_event
from app.llm.groq_client import llm_available
from app.llm.structured_output import structured_invoke
from app.core.validators import parse_profile_changes
from app.utils.identifiers import find_ids

log = logging.getLogger(__name__)

IntentLit = Literal["order_tracking", "order_cancellation", "product_information", "payment_status", "refund_status",
                    "refund_request", "complaint", "return_request", "replacement_request", "warranty_issue",
                    "general_support", "identity_verification", "clarification_required", "human_escalation","end_conversation",
                    "profile_info", "profile_update", "order_address_update"]
CATEGORIES = {"delivery_delay", "damaged_item", "wrong_item", "missing_item", "payment_issue", "return_request",
              "replacement_request", "warranty_query", "address_change", "complaint", "human_escalation"}


class AddressChange(BaseModel):
    line1: str | None = None
    line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None


class ProfileChanges(BaseModel):
    full_name: str | None = None
    email: str | None = None
    mobile_number: str | None = None
    address: AddressChange | None = None


class SupervisorDecision(BaseModel):
    intent: IntentLit
    agents: list[Literal["order", "product", "payment", "refund", "complaint", "profile"]] = Field(default_factory=list)
    profile_changes: ProfileChanges | None = None
    order_id: str | None = None
    product_query: str | None = None
    complaint_category: str | None = None
    confidence: float = 0.8


# ------------------------------------------ rule-based classifier ------------------------------------------
_STOP = set("""the a an my me i is are was were to of for and or in on at it this that these those one please
hi hello hey thanks thank you your where when what which how can could would will do does did have has had been be
want need like about with from by status order orders item product products kab kahan mera meri mere ka ki ke hai hain
ho kya mujhe chahiye aur ek wala wali se ko ne par abhi still yet pls tell show give know check track
delivery deliver delivered arrive arrived late delayed refund payment paid cancel cancelled return replace replacement
warranty price stock available availability cost damaged broken wrong missing complaint issue problem not no yes
but failed deducted come speak manager human stopped working money back late through hold""".split())

_RULES: list[tuple[str, list[str]]] = [
    ("human_escalation", ["human", "real person", "manager", "supervisor", "escalate", "insaan", "इंसान", "मैनेजर"]),
    ("order_cancellation", ["cancel", "कैंसल", "रद्द", "रद्द करा"]),
    ("return_request", ["return", "वापस", "रिटर्न"]),
    ("replacement_request", ["replace", "replacement", "exchange", "रिप्लेस", "बदलकर"]),
    ("warranty_issue", ["warranty", "guarantee", "stopped working", "not working", "वारंटी", "kharab ho gaya", "खराब हो गया"]),
    ("complaint", ["damaged", "broken", "defective", "wrong item", "wrong product", "missing", "not received",
                   "complaint", "टूटा", "खराब", "गलत", "complain", "torn", "cracked"]),
    ("payment_status", ["payment", "paid", "deducted", "debited", "charged", "transaction", "upi", "पैसे कट",
                        "भुगतान", "पेमेंट", "paisa kat", "money was taken"]),
    ("refund_status", ["refund", "रिफंड", "पैसे वापस", "money back"]),
    ("order_tracking", ["where is", "track", "status", "delivery", "deliver", "arrive", "when will", "kab", "kahan",
                        "order", "ऑर्डर", "कहाँ", "कब", "shipped", "dispatch"]),
    ("product_information", ["price", "stock", "available", "availability", "specs", "tell me about", "cost",
                             "how much", "colour", "color", "catalogue", "कीमत"]),
    ("general_support", ["hello", "hi", "thanks", "thank you", "help", "namaste", "नमस्ते", "bye", "धन्यवाद"]),
]
_REFUND_REQUEST = ["want a refund", "need a refund", "give me a refund", "refund me", "refund chahiye", "initiate",
                   "process my refund", "start a refund", "i want my money", "refund karo", "refund do"]
_CATEGORY_RULES = [("damaged_item", ["damaged", "broken", "defective", "cracked", "torn", "टूटा"]),
                   ("wrong_item", ["wrong item", "wrong product", "different product", "गलत"]),
                   ("missing_item", ["missing", "not in the box", "not received item", "one item"]),
                   ("delivery_delay", ["late", "delay", "not arrived", "haven't received", "not received"]),
                   ("address_change", ["address"]), ("payment_issue", ["payment", "deducted", "charged"])]


_PRODUCT_INTENTS = {"order_tracking", "order_cancellation", "product_information", "complaint", "return_request",
                    "replacement_request", "warranty_issue", "refund_request", "refund_status", "payment_status",
                    "order_address_update"}


_BYE = ["bye", "goodbye", "good bye", "thank you", "thanks", "thankyou", "that's all", "thats all",
        "that is all", "nothing else", "no more", "have a nice day", "see you", "dhanyavad", "shukriya",
        "alvida", "बाय", "धन्यवाद", "शुक्रिया", "अलविदा", "बस इतना", "आभार"]


def is_goodbye(text: str) -> bool:
    t = (text or "").lower().strip()
    if not t or "?" in t or len(t.split()) > 10:
        return False
    if not any(_hit(t, k) for k in _BYE):
        return False
    return not any(_hit(t, k) for name, kws in _RULES if name != "general_support" for k in kws)


def _hit(text: str, kw: str) -> bool:
    """Short ASCII keywords match whole words only ('hi' must not match 'ship')."""
    if kw.isascii() and len(kw) <= 3:
        return re.search(rf"\b{re.escape(kw)}\b", text) is not None
    return kw in text


_CHANGE_WORDS = ["change", "update", "edit", "correct", "modify", "set my", "badal", "बदल", "सुधार"]
_INFO_PHRASES = ["what is my", "what's my", "whats my", "tell me my", "my registered", "show my", "read my", "which address"]
_PROFILE_WORDS = ["address", "email", "e-mail", "mobile", "phone", "number", " name"]


def _profile_intent(t: str, original: str) -> str | None:
    """Rule-based detection of profile edits / reads (the LLM path decides this itself)."""
    if not any(_hit(t, k) for k in _CHANGE_WORDS):
        if any(p in t for p in _INFO_PHRASES) and any(k in f" {t}" for k in _PROFILE_WORDS + ["details", "profile"]):
            return "profile_info"
        return None
    has_order = bool(find_ids(original, "ORD")) or "order" in t
    if "delivery address" in t or "shipping address" in t or ("address" in t and has_order):
        return "order_address_update"
    if any(k in f" {t}" for k in _PROFILE_WORDS):
        return "profile_update"
    return None


def rule_based_decision(text: str, pending: dict | None = None) -> SupervisorDecision:
    t = (text or "").lower()
    if pending and pending.get("field") and pending.get("intent") in ("profile_update", "order_address_update"):
        # the agent just asked for the new value: this message is the answer, whatever words it contains
        return SupervisorDecision(intent=pending["intent"], agents=[], order_id=(find_ids(text, "ORD") or [None])[0],
                                  confidence=0.5)
    pi = _profile_intent(t, text)
    if pi:
        return SupervisorDecision(intent=pi, agents=[], order_id=(find_ids(text, "ORD") or [None])[0], confidence=0.5)
    intent = None
    if "refund" in t or "रिफंड" in t:
        intent = "refund_request" if any(p in t for p in _REFUND_REQUEST) else None
    if intent is None:
        for name, kws in _RULES:
            if any(_hit(t, k) for k in kws):
                intent = name
                break
    if intent == "general_support" and pending:
        intent = None
    if intent is None:
        intent = pending["intent"] if pending else "clarification_required"
    toks = [w for w in re.findall(r"[a-z0-9]+", t) if len(w) > 2 and w not in _STOP]
    oid = (find_ids(text, "ORD") or [None])[0]
    category = None
    if intent in {"complaint", "return_request", "replacement_request", "warranty_issue", "human_escalation"}:
        category = {"return_request": "return_request", "replacement_request": "replacement_request",
                    "warranty_issue": "warranty_query", "human_escalation": "human_escalation"}.get(intent)
        if category is None:
            category = next((c for c, kws in _CATEGORY_RULES if any(k in t for k in kws)), "complaint")
    elif "late" in t or "delay" in t:
        category = "delivery_delay"
    pq = " ".join(toks[:3]) or None
    if intent not in _PRODUCT_INTENTS:
        pq = None
    if oid and pq:
        pq = None if pq.startswith("ord") else pq
    return SupervisorDecision(intent=intent, agents=[], order_id=oid, product_query=pq, complaint_category=category,
                              confidence=0.5)


# ------------------------------------------------- node -------------------------------------------------
def _history_text(state: AgentState, n: int = 6) -> str:
    out = []
    for m in (state.get("conversation_history") or [])[-n - 1:-1]:
        role = "Customer" if m.type == "human" else "Agent"
        out.append(f"{role}: {str(m.content)[:300]}")
    return "\n".join(out)


async def _llm_decision(state: AgentState, msg: str) -> SupervisorDecision:
    ctx = []
    pc0 = state.get("pending_clarification") or {}
    if pc0.get("field"):
        ctx.append(f"The agent just asked the customer for the NEW {pc0['field']} (intent '{pc0.get('intent')}'). "
                   f"If the message supplies it, keep that intent and put it in profile_changes.")
    elif state.get("pending_clarification"):
        pc = state["pending_clarification"]
        ctx.append(f"The agent just asked which order the customer meant for intent '{pc.get('intent')}'. "
                   f"Candidates: {pc.get('candidates')}. A short reply like 'the laptop' answers that - keep the intent.")
    if state.get("focus_order_id"):
        ctx.append(f"Order currently being discussed: {state['focus_order_id']}")
    human = (f"Recent turns:\n{_history_text(state)}\n\n" + ("\n".join(ctx) + "\n\n" if ctx else "")
             + f"Latest customer message:\n{msg}")
    return await structured_invoke(SupervisorDecision, [("system", SUPERVISOR_SYSTEM), ("human", human)], role="supervisor")


async def supervisor_node(state: AgentState) -> dict:
    conv = state["conversation_id"]
    msg = state.get("current_user_message", "")
    await emit_event(conv, "supervisor_started", agent="supervisor", summary="Classifying request")
    source = "rules"
    decision: SupervisorDecision | None = None

    if is_goodbye(msg):
        await emit_event(conv, "intent_classified", agent="supervisor", summary="Intent: end_conversation",
                         data={"intent": "end_conversation", "source": "rules"})
        return {"current_intent": "end_conversation", "entities": {}, "agent_queue": [], "completed_agents": [],
                "active_agent": "supervisor", "end_call": not state.get("pending_action")}
    
    if llm_available():
        try:
            decision = await _llm_decision(state, msg)
            source = "llm"
        except Exception as exc:  # noqa: BLE001
            log.warning("supervisor LLM failed, using rules: %s", exc)
    if decision is None:
        decision = rule_based_decision(msg, state.get("pending_clarification"))

    intent = decision.intent if decision.intent in INTENTS else "clarification_required"
    pend = state.get("pending_clarification") or {}
    hint = pend.get("field")
    if hint and intent not in ("profile_update", "order_address_update") and pend.get("intent") in ("profile_update", "order_address_update") \
            and parse_profile_changes(msg, hint):
        intent = pend["intent"]                      # the customer is answering the agent's question
    profile_changes: dict = {}
    if intent in ("profile_update", "order_address_update"):
        if decision.profile_changes:
            profile_changes = decision.profile_changes.model_dump(exclude_none=True)
            if not profile_changes.get("address"):
                profile_changes.pop("address", None)
        if not profile_changes:
            profile_changes = parse_profile_changes(msg, hint)
        if intent == "order_address_update":
            profile_changes = {"address": profile_changes["address"]} if profile_changes.get("address") else {}
    oid = decision.order_id.upper() if decision.order_id and re.match(r"^ORD\d{4,}$", decision.order_id, re.I) else None
    cat = decision.complaint_category if decision.complaint_category in CATEGORIES else None
    queue = plan_agents(intent, decision.agents)
    entities = {"order_id": oid, "product_query": (decision.product_query or "").strip() or None,
                "complaint_category": cat,
                "profile_changes": profile_changes}
    await emit_event(conv, "intent_classified", agent="supervisor",
                     summary=f"Intent: {intent} -> {', '.join(queue) or 'direct response'}",
                     data={"intent": intent, "agents": queue, "source": source})
    return {"current_intent": intent, "entities": entities, "agent_queue": queue, "completed_agents": [],
            "active_agent": "supervisor","end_call": intent == "end_conversation" and not state.get("pending_action"),}
