"""Order Agent (+ shared order-resolution helper used by the other specialists)."""
from __future__ import annotations

from app.agents.state import AgentState, TurnTools, merge_result
from app.core.logging import emit_event
from app.guardrails.action_confirmation import propose_action

ACTIVE = {"placed", "processing", "shipped", "delayed"}


def brief(o: dict) -> dict:
    return {"order_id": o["order_id"], "order_status": o["order_status"], "order_date": o["order_date"],
            "items": [i["product_name"] for i in o["items"]]}


async def resolve_target_order(state: AgentState, tools: TurnTools, *, prefer_active: bool = True) -> dict:
    """Decide which order the customer means. Returns one of:
    {'order_id'} | {'candidates', 'reason'} | {'no_orders': True}"""
    ent = state.get("entities") or {}
    if ent.get("order_id"):
        return {"order_id": ent["order_id"]}
    orders: list[dict] | None = None
    pq = ent.get("product_query")
    if pq:
        hits = (await tools("find_orders_by_product", query=pq)).get("data") or []
        if len(hits) == 1:
            return {"order_id": hits[0]["order_id"]}
        if len(hits) > 1:
            return {"candidates": [brief(o) for o in hits[:5]], "reason": "multiple_matches"}
        reason_override = "no_product_match"
    else:
        reason_override = None
        if state.get("focus_order_id"):
            return {"order_id": state["focus_order_id"]}
    orders = (await tools("get_customer_orders", limit=20)).get("data") or []
    if not orders:
        return {"no_orders": True}
    if len(orders) == 1:
        return {"order_id": orders[0]["order_id"]}
    pool = [o for o in orders if o["order_status"] in ACTIVE] if prefer_active else []
    if len(pool) == 1 and not reason_override:
        return {"order_id": pool[0]["order_id"]}
    return {"candidates": [brief(o) for o in (pool or orders)[:5]], "reason": reason_override or "multiple_orders"}


def clarification_update(state: AgentState, target: dict) -> dict:
    return {"pending_clarification": {"intent": state.get("current_intent"),
                                      "candidates": [c["order_id"] for c in target["candidates"]]},
            "candidate_order_ids": [c["order_id"] for c in target["candidates"]]}


def resolved_update(order_id: str) -> dict:
    return {"focus_order_id": order_id, "pending_clarification": None, "candidate_order_ids": []}


async def order_agent_node(state: AgentState) -> dict:
    conv, intent = state["conversation_id"], state.get("current_intent")
    await emit_event(conv, "specialist_started", agent="order", summary="Order agent started")
    tools = TurnTools(state, "order")
    result: dict = {"intent": intent}
    extra: dict = {}
    target = await resolve_target_order(state, tools)
    if target.get("no_orders"):
        result["error"] = "No orders were found on this account."
    elif "candidates" in target:
        result["clarification"] = {"reason": target["reason"], "candidates": target["candidates"]}
        extra = clarification_update(state, target)
    else:
        oid = target["order_id"]
        det = await tools("get_order_details", order_id=oid)
        if not det["ok"]:
            result["error"] = det["message"]
            extra = {"pending_clarification": None}
        else:
            result["order"] = det["data"]
            trk = await tools("get_order_tracking", order_id=oid)
            result["tracking"] = trk.get("data")
            extra = resolved_update(oid)
            if intent == "order_cancellation":
                elig = await tools("check_cancellation_eligibility", order_id=oid)
                result["cancellation"] = elig.get("data")
                if elig["ok"] and elig["data"]["eligible"]:
                    items = ", ".join(i["product_name"] for i in det["data"]["items"])
                    summary = (f"Cancel order {oid} ({items}). If a payment was captured, a refund will be "
                               f"requested to the original payment method.")
                    pa = await propose_action(conv, state["customer_id"], "cancel_order", {"order_id": oid}, summary)
                    result["proposed_action"] = {"summary": summary, "action_type": "cancel_order"}
                    extra["pending_action"] = pa
    await emit_event(conv, "specialist_completed", agent="order", summary="Order agent finished")
    return merge_result(state, "order", result, tools, **extra)
