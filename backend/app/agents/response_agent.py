"""Response Agent: turns verified facts into a short, spoken, language-matched reply."""
from __future__ import annotations

import json
import logging

from app.agents.prompts import RESPONSE_SYSTEM, RESPONSE_USER
from app.agents.state import AgentState
from app.core.logging import emit_event
from app.llm.groq_client import llm_available
from app.llm.structured_output import text_invoke
from app.utils.formatting import clean_for_speech, money
from app.voice.language_config import get_language

log = logging.getLogger(__name__)
_DROP = {"shipping_address", "scenario_note", "transaction_reference", "currency", "customer_id", "source"}


def _trim(obj):
    if isinstance(obj, dict):
        return {k: _trim(v) for k, v in obj.items() if k not in _DROP and v is not None}
    if isinstance(obj, list):
        return [_trim(v) for v in obj]
    return obj


def build_facts(state: AgentState) -> dict:
    facts: dict = {"intent": state.get("current_intent"), "results": _trim(state.get("agent_results", {}))}
    prof = state.get("customer_profile") or {}
    if prof.get("first_name"):
        facts["customer_first_name"] = prof["first_name"]
    if state.get("notices"):
        facts["notices"] = state["notices"]
    pa = (state.get("agent_results", {}).get("order") or {}).get("proposed_action") \
        or next((r["proposed_action"] for r in state.get("agent_results", {}).values()
                 if isinstance(r, dict) and r.get("proposed_action")), None)
    if pa:
        facts["proposed_action"] = pa
    conf = state.get("agent_results", {}).get("confirmation")
    if conf:
        facts["confirmation_result"] = _trim(conf)
    if state.get("end_call"):
        facts["notices"] = [*facts.get("notices", []), {"type": "goodbye"}]
    return facts


def _recent_turns(state: AgentState, n: int = 4) -> str:
    return "\n".join(f"{'Customer' if m.type == 'human' else 'Agent'}: {str(m.content)[:200]}"
                     for m in (state.get("conversation_history") or [])[-n - 1:-1])


def _script_note(key: str | None) -> str:
    cfg = get_language(key)
    if cfg is None or cfg.key == "english":
        return "Write in simple English."
    if cfg.key == "hinglish":
        return "Write Hindi words in Roman script mixed naturally with English (Hinglish). No Devanagari."
    return f"Write in {cfg.name} using its native script ({cfg.native_name}); keep IDs, amounts and dates in Latin digits."


# --------------------------------------- deterministic fallback (English) ---------------------------------------
def _fmt_items(order: dict) -> str:
    return ", ".join(i["product_name"] if isinstance(i, dict) else str(i) for i in order.get("items", []))


def render_fallback(facts: dict) -> str:
    parts: list[str] = []
    for n in facts.get("notices", []):
        t = n.get("type")
        parts.append({"ask_mobile": "Please tell me the 10-digit mobile number registered with your account.",
                      "identity_verified": "Thank you, you're verified. How can I help you today?",
                      "identity_failed": "I couldn't verify that number. Please try again with your registered mobile number.",
                      "blocked": "I can only help with your own orders, payments, refunds and support requests. How can I help?",
                      "general": "I can help with orders, payments, refunds, products and complaints. What do you need?",
                      "goodbye": "Thank you for contacting us. Have a great day. Goodbye!",
                      "no_pending_action": "There is nothing waiting for your confirmation right now."}.get(t, ""))
    res = facts.get("results", {})
    conf = facts.get("confirmation_result")
    if conf:
        st = conf.get("status")
        r = conf.get("result") or {}
        if st == "executed":
            if "ticket_id" in r:
                parts.append(f"Done. Your ticket {r['ticket_id']} has been registered.")
            elif r.get("new_status") == "cancelled":
                parts.append(f"Done. Order {r['order_id']} is cancelled." + (
                    f" A refund {r['refund']['refund_id']} of {money(r['refund']['amount'])} has been requested."
                    if r.get("refund") else ""))
            elif "refund_id" in r:
                parts.append(f"Done. Refund {r['refund_id']} of {money(r['amount'])} has been requested.")
            elif r.get("changes"):
                parts.append("Done. " + "; ".join(f"Your {k.replace('_', ' ')} is now {x['new']}" for k, x in r["changes"].items()) + ".")
        elif st == "rejected":
            parts.append("Okay, I haven't made any changes.")
        else:
            parts.append(conf.get("message") or "I couldn't complete that action.")
    for name, r in res.items():
        if name == "confirmation" or not isinstance(r, dict):
            continue
        if r.get("error"):
            parts.append(r["error"]); continue
        if r.get("profile"):
            p = r["profile"]
            parts.append(f"We have {p['full_name']} on file, email {p['email']}, mobile {p['mobile_masked']}, address {p['address']}.")
        if r.get("needs_value"):
            nv = r["needs_value"]
            parts.append(f"Please tell me the new {', '.join(nv['fields'])}." + (f" Say it as {nv['address_format']}." if 'address' in nv['fields'] else ""))
        if r.get("validation_errors"):
            parts.append("That didn't look right: " + "; ".join(r["validation_errors"].values()) + " Please say it again.")
        if r.get("no_change"):
            parts.append("Those details are already exactly that, so there is nothing to update.")
        if r.get("clarification"):
            c = r["clarification"]
            if c.get("candidates"):
                opts = "; ".join(f"{x['order_id']} ({', '.join(x['items'])})" for x in c["candidates"])
                parts.append(f"Which order do you mean? {opts}.")
            else:
                parts.append("Which product do you mean?")
            continue
        o = r.get("order")
        if o:
            tr = r.get("tracking") or {}
            line = f"Order {o['order_id']} ({_fmt_items(o)}) is {o['order_status'].replace('_', ' ')}."
            if tr.get("estimated_delivery_date") and o["order_status"] != "delivered":
                line += f" Estimated delivery is {tr['estimated_delivery_date']}."
            if o.get("delivered_at"):
                line += f" It was delivered on {o['delivered_at']}."
            parts.append(line)
        if r.get("cancellation") and not r["cancellation"].get("eligible"):
            parts.append(r["cancellation"]["reason"])
        for p in r.get("payments", []) or []:
            parts.append(f"Payment {p['payment_id']} for order {p['order_id']}: {money(p['amount'])}, {p['payment_status']}.")
        for rf in r.get("refunds", []) or []:
            line = f"Refund {rf['refund_id']} for order {rf['order_id']} of {money(rf['refund_amount'])} is {rf['refund_status']}."
            if rf.get("estimated_completion_date"):
                line += f" Expected by {rf['estimated_completion_date']}."
            parts.append(line)
        if r.get("eligibility") and not r["eligibility"].get("eligible"):
            parts.append(r["eligibility"]["reason"])
        for p in r.get("products", []) or []:
            parts.append(f"{p['name']} costs {money(p['unit_price'])}; {p['stock_quantity']} in stock."
                         + (f" Warranty: {p['warranty_period']}." if p.get("warranty_period") else ""))
        for w in r.get("product_warranty", []) or []:
            parts.append(f"{w['name']} has a warranty of {w['warranty_period']}.")
        if r.get("duplicate_ticket"):
            d = r["duplicate_ticket"]
            parts.append(f"You already have an open ticket {d['ticket_id']} for this ({d['ticket_status'].replace('_', ' ')}).")
    pa = facts.get("proposed_action")
    if pa:
        parts.append(f"I can do this: {pa['summary']}. Shall I go ahead? Please say yes or no.")
    return " ".join(p for p in parts if p) or "How can I help you with your orders, payments or refunds?"


# --------------------------------------------------- node ---------------------------------------------------
async def response_agent_node(state: AgentState) -> dict:
    conv = state["conversation_id"]
    facts = build_facts(state)
    lang = state.get("selected_language")
    text: str | None = None
    fallback = False
    if llm_available():
        try:
            cfg = get_language(lang)
            system = RESPONSE_SYSTEM.format(language_name=cfg.name if cfg else "English", script_note=_script_note(lang))
            fb = state.get("output_feedback")
            human = RESPONSE_USER.format(
                facts=json.dumps(facts, ensure_ascii=False, default=str),
                message=state.get("current_user_message") or "(no message)",
                feedback=(f"\nYour previous reply was rejected: {fb}. Rewrite it using only values from FACTS."
                          if fb else ""))
            recent = _recent_turns(state)
            if recent:
                human = f"RECENT TURNS:\n{recent}\n\n" + human
            text = clean_for_speech(await text_invoke([("system", system), ("human", human)], role="response"))
        except Exception as exc:  # noqa: BLE001
            log.warning("response LLM failed, using deterministic fallback: %s", exc)
    if not text:
        text, fallback = render_fallback(facts), True
    await emit_event(conv, "response_generated", agent="response", summary="Response drafted" + (" (fallback)" if fallback else ""))
    return {"response": text, "response_from_fallback": fallback, "active_agent": "response"}
