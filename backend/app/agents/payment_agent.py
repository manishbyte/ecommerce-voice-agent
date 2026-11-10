"""Payment Agent: payment history/status and explanations of failed or pending transactions."""
from __future__ import annotations

from app.agents.order_agent import resolve_target_order, resolved_update
from app.agents.state import AgentState, TurnTools, merge_result
from app.core.logging import emit_event


async def payment_agent_node(state: AgentState) -> dict:
    conv = state["conversation_id"]
    await emit_event(conv, "specialist_started", agent="payment", summary="Payment agent started")
    tools = TurnTools(state, "payment")
    ent = state.get("entities") or {}
    result: dict = {}
    extra: dict = {}
    oid = ent.get("order_id")
    if not oid and ent.get("product_query"):
        t = await resolve_target_order(state, tools)
        oid = t.get("order_id")
    res = await tools("get_payment_status", order_id=oid) if oid else await tools("get_payment_status")
    if res["ok"]:
        result["payments"] = res["data"]
        failed = [p for p in res["data"] if p["payment_status"] != "captured"]
        if failed:
            result["attention"] = [{"payment_id": p["payment_id"], "order_id": p["order_id"],
                                    "payment_status": p["payment_status"], "explanation": p["explanation"]} for p in failed]
        if oid:
            extra = resolved_update(oid)
    else:
        result["error"] = res["message"]
    await emit_event(conv, "specialist_completed", agent="payment", summary="Payment agent finished")
    return merge_result(state, "payment", result, tools, **extra)
