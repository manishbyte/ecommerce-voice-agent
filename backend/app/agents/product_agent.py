"""Product Agent: catalogue lookups (public data) and stock availability."""
from __future__ import annotations

from app.agents.state import AgentState, TurnTools, merge_result
from app.core.logging import emit_event


async def product_agent_node(state: AgentState) -> dict:
    conv = state["conversation_id"]
    await emit_event(conv, "specialist_started", agent="product", summary="Product agent started")
    tools = TurnTools(state, "product")
    ent = state.get("entities") or {}
    result: dict = {}
    query = ent.get("product_query")
    if query:
        res = await tools("get_product_details", query=query)
        result["products"] = res.get("data") if res["ok"] else None
        if not res["ok"]:
            result["error"] = res["message"]
    elif state.get("focus_order_id") or ent.get("order_id"):
        oid = ent.get("order_id") or state["focus_order_id"]
        det = await tools("get_order_details", order_id=oid)
        if det["ok"]:
            found = []
            for it in det["data"]["items"][:2]:
                p = await tools("get_product_details", product_id=it["product_id"])
                if p["ok"]:
                    found.extend(p["data"])
            result["products"] = found
            result["from_order"] = oid
        else:
            result["error"] = det["message"]
    else:
        result["clarification"] = {"reason": "which_product"}
    await emit_event(conv, "specialist_completed", agent="product", summary="Product agent finished")
    return merge_result(state, "product", result, tools)
