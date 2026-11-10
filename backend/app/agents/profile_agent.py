"""Profile Agent: read / edit the customer's own details and an order's delivery address (always with confirmation).

* profile_info          -> read-only answer from the database
* profile_update        -> validate, read the change back, propose `update_profile` (needs yes)
* order_address_update  -> only placed/processing orders, propose `update_order_address` (needs yes)
Email / mobile changes are flagged `sensitive` so the response explicitly warns before asking for the yes.
"""
from __future__ import annotations

from app.agents.order_agent import clarification_update, resolve_target_order, resolved_update
from app.agents.state import AgentState, TurnTools, merge_result
from app.core import validators as v
from app.core.logging import emit_event
from app.core.security import mask_mobile
from app.guardrails.action_confirmation import propose_action

LABELS = {"full_name": "name", "email": "email address", "mobile_number": "mobile number",
          "preferred_language": "preferred language", "address": "address"}


def _pending(intent: str, field: str | None, **extra) -> dict:
    return {"pending_clarification": {"intent": intent, "field": field, **extra}}


def _describe(field: str, current: dict, new) -> tuple[str, str]:
    """(old_text, new_text) as they will be read aloud."""
    if field == "address":
        return v.format_address(current.get("address")), v.format_address(v.merge_address(current.get("address"), new))
    if field == "mobile_number":
        return mask_mobile(current.get("mobile_number", "")), new
    return str(current.get(field) or "-"), str(new)


async def profile_agent_node(state: AgentState) -> dict:
    conv, intent = state["conversation_id"], state.get("current_intent")
    await emit_event(conv, "specialist_started", agent="profile", summary="Profile agent started")
    tools = TurnTools(state, "profile")
    ent = state.get("entities") or {}
    changes = ent.get("profile_changes") or {}
    hint = (state.get("pending_clarification") or {}).get("field")
    result: dict = {"intent": intent}
    extra: dict = {}

    cur_res = await tools("get_profile_details")
    if not cur_res["ok"]:
        result["error"] = "I couldn't load your details right now."
        return merge_result(state, "profile", result, tools, pending_clarification=None)
    current = cur_res["data"]

    if intent == "profile_info":
        result["profile"] = {"full_name": current["full_name"], "email": current["email"],
                             "mobile_masked": current["mobile_masked"], "address": current["address_text"],
                             "preferred_language": current["preferred_language"]}
        extra = {"pending_clarification": None}

    elif intent == "profile_update":
        clean, errors = v.validate_profile_changes(changes)
        if errors:
            result["validation_errors"] = errors
            extra = _pending(intent, next(iter(errors)))
        elif not clean:
            fields = v.mentioned_fields(state.get("current_user_message", ""))
            result["needs_value"] = {"fields": fields or ["name, email, mobile number or address"],
                                     "address_format": "house/flat and street, city, state and 6-digit PIN code"}
            extra = _pending(intent, fields[0] if fields else None)
        else:
            diff = v.diff_changes(current, clean)
            if not diff:
                result["no_change"] = True
                extra = {"pending_clarification": None}
            else:
                lines, sensitive = [], [f for f in diff if f in v.SENSITIVE_FIELDS]
                for f, new in diff.items():
                    old_t, new_t = _describe(f, current, new)
                    lines.append(f"{LABELS[f]} from {old_t} to {new_t}")
                summary = "Update your " + "; ".join(lines)
                if sensitive:
                    summary += (". These are the details we use to verify you, so please confirm only if they are "
                                "exactly right")
                pa = await propose_action(conv, state["customer_id"], "update_profile", {"changes": diff}, summary)
                result["proposed_action"] = {"summary": summary, "action_type": "update_profile",
                                             "sensitive_fields": [LABELS[f] for f in sensitive]}
                extra = {"pending_action": pa, "pending_clarification": None}

    else:  # order_address_update
        target = await resolve_target_order(state, tools, prefer_active=True)
        if target.get("no_orders"):
            result["error"] = "No orders were found on this account."
        elif "candidates" in target:
            result["clarification"] = {"reason": target["reason"], "candidates": target["candidates"]}
            extra = clarification_update(state, target)
            extra["pending_clarification"]["field"] = None
        else:
            oid = target["order_id"]
            extra = resolved_update(oid)
            elig = await tools("check_order_address_edit", order_id=oid)
            if not elig["ok"]:
                result["error"] = elig["message"]
            elif not elig["data"]["eligible"]:
                result["eligibility"] = {k: elig["data"][k] for k in ("order_id", "order_status", "eligible", "reason")}
            else:
                addr = changes.get("address")
                if not addr:
                    result["needs_value"] = {"fields": ["address"], "order_id": oid,
                                             "current_address": elig["data"]["current_address_text"],
                                             "address_format": "house/flat and street, city, state and 6-digit PIN code"}
                    extra = {**extra, **_pending(intent, "address")}
                else:
                    clean, errs = v.validate_address(addr, partial_ok=True)
                    if errs:
                        result["validation_errors"] = errs
                        extra = {**extra, **_pending(intent, "address")}
                    else:
                        merged = v.merge_address(elig["data"]["current_address"], clean)
                        if all((merged.get(k) or None) == (elig["data"]["current_address"].get(k) or None) for k in v.ADDRESS_FIELDS):
                            result["no_change"] = True
                        else:
                            old_t, new_t = elig["data"]["current_address_text"], v.format_address(merged)
                            summary = f"Change the delivery address of order {oid} from {old_t} to {new_t}"
                            pa = await propose_action(conv, state["customer_id"], "update_order_address",
                                                      {"order_id": oid, "address": clean}, summary)
                            result["proposed_action"] = {"summary": summary, "action_type": "update_order_address"}
                            extra = {**extra, "pending_action": pa}

    await emit_event(conv, "specialist_completed", agent="profile", summary="Profile agent finished")
    return merge_result(state, "profile", result, tools, **extra)
