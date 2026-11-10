"""Action guardrail: explicit, server-side-validated confirmation of consequential actions.

* Pending actions live in PostgreSQL (authoritative) - not in model output, not in client input.
* One pending action per conversation; proposing a new one supersedes the old one.
* Confirmation is bound to (conversation, customer, action id) and expires.
* At confirmation time the action is *re-validated* against current database state, then executed
  in the same transaction that marks it as executed -> a replayed "yes" cannot run it twice.
"""
from __future__ import annotations

import re
import uuid
from datetime import timedelta

from sqlalchemy import select, update

from app.config import get_settings
from app.core import business_rules as rules
from app.core.exceptions import AppError
from app.core.logging import emit_event
from app.database.base import utcnow
from app.database.connection import get_sessionmaker
from app.models import Conversation, Customer, PendingAction
from app.utils.identifiers import ORDER_ID_RE

# ----------------------------- confirmation phrase classification (pure) -----------------------------
_YES = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed", "proceed", "correct", "right",
        "haan", "han", "haa", "ha", "ji", "theek", "thik", "karo", "kardo", "hanji", "हाँ", "हां", "जी", "ठीक", "करो",
        "होय", "hoy", "हो", "ஆம்", "சரி", "అవును", "సరే", "ಹೌದು", "ಸರಿ", "അതെ", "ശരി", "হ্যাঁ", "হ্যা", "ઠીક", "હા", "ਹਾਂ", "ਠੀਕ"}
_YES_PHRASES = ("go ahead", "do it", "kar do", "theek hai", "thik hai", "ठीक है", "कर दो", "ठीक आहे", "ਠੀਕ ਹੈ",
                "ঠিক আছে", "ઠીક છે", "yes please", "please do")
_NO = {"no", "nope", "nah", "dont", "don't", "stop", "nahi", "nahin", "nai", "na", "नहीं", "नही", "मत", "नको", "नाही",
       "இல்லை", "வேண்டாம்", "వద్దు", "కాదు", "ಬೇಡ", "ಇಲ್ಲ", "വേണ്ട", "ഇല്ല", "না", "નહીં", "ના", "ਨਹੀਂ"}
_HOLD = {"wait", "hold", "ruko", "minute", "maybe", "रुको", "unsure"}
_HOLD_PHRASES = ("not sure", "hold on", "let me think", "ek minute", "not yet")


def classify_confirmation(text: str) -> str | None:
    """'confirm' | 'reject' | None (anything that isn't a clear, short yes/no)."""
    t = (text or "").lower().strip()
    toks = [x for x in re.split(r"[\s,.!?;:।]+", t) if x]
    if not toks or len(toks) > 8:
        return None
    if any(h in toks for h in _HOLD) or any(p in t for p in _HOLD_PHRASES):
        return None
    yes = any(x in _YES for x in toks) or any(p in t for p in _YES_PHRASES)
    no = any(x in _NO for x in toks)
    if yes and no:
        return None
    if no:
        return "reject"
    if yes:
        return "confirm"
    return None


# ----------------------------------------- persistence --------------------------------------------
def _public(a: PendingAction) -> dict:
    return {"action_id": str(a.id), "action_type": a.action_type, "params": a.params, "summary": a.summary,
            "status": a.status, "expires_at": a.expires_at.isoformat()}


def _validate_params(action_type: str, params: dict) -> None:
    if action_type not in rules.ACTION_TYPES:
        raise AppError(f"unknown action type {action_type}", code="invalid_action")
    if action_type in {"cancel_order", "request_refund"} and not ORDER_ID_RE.match(params.get("order_id", "")):
        raise AppError("order_id required", code="invalid_action")
    if action_type == "update_profile":
        if not isinstance(params.get("changes"), dict) or not params["changes"]:
            raise AppError("changes required", code="invalid_action")
    if action_type == "update_order_address":
        if not ORDER_ID_RE.match(params.get("order_id", "")) or not isinstance(params.get("address"), dict):
            raise AppError("order_id and address required", code="invalid_action")
    if action_type == "create_ticket":
        if params.get("category") not in rules.TICKET_CATEGORIES:
            raise AppError("invalid ticket category", code="invalid_action")
        if not params.get("subject") or not params.get("description"):
            raise AppError("subject and description required", code="invalid_action")
        if params.get("order_id") and not ORDER_ID_RE.match(params["order_id"]):
            raise AppError("bad order id", code="invalid_action")


async def propose_action(conversation_id: str, customer_id: str, action_type: str, params: dict, summary: str) -> dict:
    _validate_params(action_type, params)
    ttl = get_settings().pending_action_ttl_seconds
    async with get_sessionmaker()() as s:
        async with s.begin():
            conv = await s.get(Conversation, uuid.UUID(conversation_id))
            cust = (await s.execute(select(Customer).where(Customer.customer_id == customer_id))).scalar_one_or_none()
            if conv is None or cust is None or conv.customer_pk != cust.id:
                raise AppError("conversation/customer mismatch", code="invalid_action")
            await s.execute(update(PendingAction).where(PendingAction.conversation_pk == conv.id,
                                                        PendingAction.status == "pending")
                            .values(status="superseded", resolved_at=utcnow()))
            now = utcnow()
            pa = PendingAction(conversation_pk=conv.id, customer_pk=cust.id, action_type=action_type, params=params,
                               summary=summary, status="pending", created_at=now, expires_at=now + timedelta(seconds=ttl))
            s.add(pa)
            await s.flush()
            out = _public(pa)
    await emit_event(conversation_id, "action_confirmation_requested", status="pending", summary=summary,
                     data={"action_id": out["action_id"], "action_type": action_type})
    return out


async def get_pending_action(conversation_id: str) -> dict | None:
    """Latest unexpired pending action for the conversation (expires stale ones as a side effect)."""
    async with get_sessionmaker()() as s:
        async with s.begin():
            now = utcnow()
            await s.execute(update(PendingAction).where(PendingAction.conversation_pk == uuid.UUID(conversation_id),
                                                        PendingAction.status == "pending",
                                                        PendingAction.expires_at < now)
                            .values(status="expired", resolved_at=now))
            row = (await s.execute(select(PendingAction).where(PendingAction.conversation_pk == uuid.UUID(conversation_id),
                                                               PendingAction.status == "pending")
                                   .order_by(PendingAction.created_at.desc()).limit(1))).scalar_one_or_none()
            return _public(row) if row else None


async def confirm_pending_action(conversation_id: str, decision: str, action_id: str | None = None) -> dict:
    """Confirm or reject the pending action. Returns {'ok', 'status', ...} - never raises for business outcomes."""
    from app.tools import order_tools, profile_tools, refund_tools, ticket_tools

    if decision not in {"confirm", "reject"}:
        return {"ok": False, "status": "invalid", "message": "decision must be confirm or reject"}
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        return {"ok": False, "status": "invalid", "message": "bad conversation id"}

    outcome: dict
    async with get_sessionmaker()() as s:
        async with s.begin():
            conv = await s.get(Conversation, conv_uuid)
            if conv is None or conv.customer_pk is None:
                return {"ok": False, "status": "no_conversation", "message": "conversation not found or unverified"}
            customer = await s.get(Customer, conv.customer_pk)
            row = (await s.execute(select(PendingAction).where(PendingAction.conversation_pk == conv.id,
                                                               PendingAction.status == "pending")
                                   .order_by(PendingAction.created_at.desc()).limit(1).with_for_update())).scalar_one_or_none()
            if row is None:
                return {"ok": False, "status": "no_pending_action", "message": "There is no action waiting for confirmation."}
            if action_id and str(row.id) != action_id:      # stale / replayed confirmation for a different action
                return {"ok": False, "status": "stale_action", "message": "That confirmation does not match the current pending action."}
            if row.customer_pk != conv.customer_pk:
                return {"ok": False, "status": "mismatch", "message": "pending action does not belong to this customer"}
            now = utcnow()
            if row.expires_at < now:
                row.status, row.resolved_at = "expired", now
                outcome = {"ok": False, "status": "expired", "message": "The confirmation window has expired."}
            elif decision == "reject":
                row.status, row.resolved_at = "rejected", now
                outcome = {"ok": True, "status": "rejected", "action_type": row.action_type, "summary": row.summary}
            else:
                cid, params, atype = customer.customer_id, row.params, row.action_type
                try:
                    check = await {"cancel_order": order_tools.revalidate_cancellation,
                                   "request_refund": refund_tools.revalidate_refund,
                                   "create_ticket": ticket_tools.revalidate_ticket,
                                   "update_profile": profile_tools.revalidate_update_profile,
                                   "update_order_address": profile_tools.revalidate_order_address}[atype](s, cid, params)
                    if not check.eligible:
                        row.status, row.resolved_at = "failed", now
                        row.result = {"reason_code": check.code, "reason": check.message}
                        outcome = {"ok": False, "status": "no_longer_eligible", "action_type": atype, "message": check.message}
                    else:
                        if atype == "cancel_order":
                            result = await order_tools.execute_cancellation(s, cid, params)
                        elif atype == "request_refund":
                            result = await refund_tools.execute_refund_request(s, cid, params)
                        elif atype == "update_profile":
                            result = await profile_tools.execute_update_profile(s, cid, params, conversation_id)
                        elif atype == "update_order_address":
                            result = await profile_tools.execute_order_address(s, cid, params, conversation_id)
                        else:
                            result = await ticket_tools.execute_create_ticket(s, cid, params, conversation_id)
                        row.status, row.resolved_at, row.result = "executed", now, result
                        outcome = {"ok": True, "status": "executed", "action_type": atype, "result": result, "summary": row.summary}
                except Exception as exc:  # noqa: BLE001  -> roll back the business change, record failure below
                    await s.rollback()
                    outcome = {"ok": False, "status": "failed", "action_type": atype, "message": f"{type(exc).__name__}: {exc}"[:200]}
    if outcome["status"] == "failed":
        async with get_sessionmaker()() as s2:
            async with s2.begin():
                await s2.execute(update(PendingAction).where(PendingAction.conversation_pk == conv_uuid,
                                                             PendingAction.status == "pending")
                                 .values(status="failed", resolved_at=utcnow()))
    await emit_event(conversation_id, "action_executed" if outcome["status"] == "executed" else "action_resolved",
                     status="ok" if outcome["ok"] else "error", summary=f"{outcome.get('action_type', '')}: {outcome['status']}",
                     data={"status": outcome["status"]})
    return outcome
