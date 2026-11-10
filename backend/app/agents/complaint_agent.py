"""Complaint Agent: complaints, returns, replacements, warranty, address changes, escalations."""
from __future__ import annotations

from app.agents.order_agent import clarification_update, resolve_target_order, resolved_update
from app.agents.state import AgentState, TurnTools, merge_result
from app.core import business_rules as rules
from app.core.logging import emit_event
from app.guardrails.action_confirmation import propose_action

LABELS = {"delivery_delay": "delivery delay", "damaged_item": "damaged item", "wrong_item": "wrong item",
          "missing_item": "missing item", "payment_issue": "payment issue", "return_request": "return",
          "replacement_request": "replacement", "warranty_query": "warranty", "address_change": "address change",
          "complaint": "complaint", "human_escalation": "escalation to a human agent"}
HIGH = {"damaged_item", "wrong_item", "missing_item", "payment_issue", "human_escalation"}
NEEDS_ORDER = {"delivery_delay", "damaged_item", "wrong_item", "missing_item", "return_request",
               "replacement_request", "warranty_query", "address_change"}
INTENT_CATEGORY = {"return_request": "return_request", "replacement_request": "replacement_request",
                   "warranty_issue": "warranty_query", "human_escalation": "human_escalation"}


async def complaint_agent_node(state: AgentState) -> dict:
    conv, intent = state["conversation_id"], state.get("current_intent")
    await emit_event(conv, "specialist_started", agent="complaint", summary="Complaint agent started")
    tools = TurnTools(state, "complaint")
    ent = state.get("entities") or {}
    category = INTENT_CATEGORY.get(intent) or ent.get("complaint_category") or "complaint"
    if category not in rules.TICKET_CATEGORIES:
        category = "complaint"
    result: dict = {"intent": intent, "category": category}
    extra: dict = {}
    oid: str | None = None

    if category in NEEDS_ORDER or ent.get("order_id") or ent.get("product_query"):
        target = await resolve_target_order(state, tools, prefer_active=category in {"delivery_delay", "address_change"})
        if "candidates" in target:
            result["clarification"] = {"reason": target["reason"], "candidates": target["candidates"]}
            extra = clarification_update(state, target)
            await emit_event(conv, "specialist_completed", agent="complaint", summary="Needs clarification")
            return merge_result(state, "complaint", result, tools, **extra)
        if target.get("no_orders"):
            result["error"] = "No orders were found on this account."
            return merge_result(state, "complaint", result, tools)
        oid = target["order_id"]
        extra = resolved_update(oid)

    # existing tickets (duplicate detection + status reporting)
    tk = await tools("get_customer_tickets", order_id=oid) if oid else await tools("get_customer_tickets", only_open=True)
    tickets = tk.get("data") or []
    result["existing_tickets"] = tickets[:5]
    dup = next((t for t in tickets if t["category"] == category and t["ticket_status"] in rules.OPEN_TICKET_STATUSES), None)

    can_create = True
    if oid:
        det = await tools("get_order_details", order_id=oid)
        if not det["ok"]:
            result["error"] = det["message"]
            return merge_result(state, "complaint", result, tools, **{"pending_clarification": None})
        result["order"] = {k: det["data"][k] for k in ("order_id", "order_status", "order_date", "estimated_delivery_date",
                                                     "delivered_at", "items")}
        if category in {"return_request", "replacement_request"}:
            el = await tools("check_return_eligibility", order_id=oid)
            result["eligibility"] = el.get("data")
            can_create = bool(el["ok"] and el["data"]["eligible"])
        elif category == "address_change":
            el = await tools("check_cancellation_eligibility", order_id=oid)   # same pre-dispatch rule
            if el["ok"]:
                result["eligibility"] = {**el["data"], "note": "Address can only be changed before dispatch."}
            can_create = bool(el["ok"] and el["data"]["eligible"])
        elif category == "warranty_query" and det["data"]["items"]:
            p = await tools("get_product_details", product_id=det["data"]["items"][0]["product_id"])
            if p["ok"]:
                result["product_warranty"] = [{"name": x["name"], "warranty_period": x["warranty_period"]} for x in p["data"]]

    if dup:
        result["duplicate_ticket"] = {"ticket_id": dup["ticket_id"], "ticket_status": dup["ticket_status"],
                                      "category": dup["category"]}
    elif can_create:
        msg = (state.get("current_user_message") or "")[:300]
        subject = f"{LABELS[category].capitalize()}" + (f" - order {oid}" if oid else "")
        description = f"Customer said (voice support): {msg}"
        params = {"order_id": oid, "category": category, "subject": subject, "description": description,
                  "priority": "high" if category in HIGH else "medium"}
        summary = f"Register a {LABELS[category]} ticket" + (f" for order {oid}" if oid else "") + \
                  (" so a human agent can follow up" if category == "human_escalation" else "")
        pa = await propose_action(conv, state["customer_id"], "create_ticket", params, summary)
        result["proposed_action"] = {"summary": summary, "action_type": "create_ticket"}
        extra["pending_action"] = pa
    await emit_event(conv, "specialist_completed", agent="complaint", summary="Complaint agent finished")
    return merge_result(state, "complaint", result, tools, **extra)
