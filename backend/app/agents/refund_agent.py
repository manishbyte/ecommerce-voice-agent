"""Refund Agent: refund status, eligibility and (confirmed) refund requests."""
from __future__ import annotations

from app.agents.order_agent import clarification_update, resolve_target_order, resolved_update
from app.agents.state import AgentState, TurnTools, merge_result
from app.core.logging import emit_event
from app.guardrails.action_confirmation import propose_action
import logging
logger = logging.getLogger(__name__)


async def refund_agent_node(state: AgentState) -> dict:
    conv, intent = state["conversation_id"], state.get("current_intent")
    logger.info("refund_agent_node started for conversation %s with intent %s", conv, intent)
    await emit_event(conv, "specialist_started", agent="refund", summary="Refund agent started")
    tools = TurnTools(state, "refund")
    ent = state.get("entities") or {}
    result: dict = {"intent": intent}
    logger.debug("Initial result dict: %s", result)
    extra: dict = {}

    if intent == "refund_status":
        logger.info("Processing refund_status intent")
        oid = ent.get("order_id") or (state.get("focus_order_id") if not ent.get("product_query") else None)
        if not oid and ent.get("product_query"):
            oid = (await resolve_target_order(state, tools)).get("order_id")
        res = await tools("get_refund_status", order_id=oid) if oid else await tools("get_refund_status")
        logger.debug("Refund status response ok=%s", res.get('ok'))
        if res["ok"]:
            result["refunds"] = res["data"]
            logger.info("Retrieved %d refunds", len(res.get('data', [])))
        else:
            result["refunds"] = []
            logger.info("No refunds found for order %s", oid)
            result["note"] = "No refund records exist for this request."
            if oid:
                el = await tools("check_refund_eligibility", order_id=oid)
                result["eligibility"] = el.get("data")
        if oid:
            extra = resolved_update(oid)
    else:  # refund_request
        target = await resolve_target_order(state, tools, prefer_active=False)
        if target.get("no_orders"):
            result["error"] = "No orders were found on this account."
            logger.warning("No orders found for account in refund request")
        elif "candidates" in target:
            result["clarification"] = {"reason": target["reason"], "candidates": target["candidates"]}
            extra = clarification_update(state, target)
        else:
            oid = target["order_id"]
            el = await tools("check_refund_eligibility", order_id=oid)
            extra = resolved_update(oid)
            if not el["ok"]:
                result["error"] = el["message"]
                logger.warning("Refund eligibility check failed: %s", el.get('message'))
            else:
                result["eligibility"] = el["data"]
                if el["data"]["eligible"]:
                    summary = (f"Request a refund of ₹{el['data']['refund_amount']:,} for order {oid}. "
                               f"This is a simulated refund record in this demo.")
                    pa = await propose_action(conv, state["customer_id"], "request_refund", {"order_id": oid}, summary)
                    result["proposed_action"] = {"summary": summary, "action_type": "request_refund"}
                    extra["pending_action"] = pa
                    logger.info("Proposed refund action for order %s", oid)
                elif el["data"]["reason_code"] == "refund_exists":
                    rs = await tools("get_refund_status", order_id=oid)
                    result["refunds"] = rs.get("data") or []
    await emit_event(conv, "specialist_completed", agent="refund", summary="Refund agent finished")
    logger.info("refund_agent_node completed for conversation %s", conv)
    return merge_result(state, "refund", result, tools, **extra)
