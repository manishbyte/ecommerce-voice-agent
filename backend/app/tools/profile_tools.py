"""Profile & order-address tools: read tools for the agent + shared write helpers.

The write helpers (`apply_profile_changes`, `apply_order_address`) are used by BOTH the dashboard API and the
voice agent's confirmed-action executors, so validation, uniqueness checks and the audit trail are identical.
"""
from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import business_rules as rules
from app.core import validators as v
from app.core.exceptions import ActionError, NotFoundError, ValidationFailed
from app.core.security import mask_mobile
from app.database.connection import get_sessionmaker
from app.guardrails.customer_authorization import get_owned_order, resolve_customer
from app.models import ChangeLog, Customer
from app.tools import fail, ok


# ------------------------------------------------------------------ audit trail
def _s(value) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def log_change(session: AsyncSession, *, entity_type: str, entity_id: str, customer_id: str, field: str, old, new,
               source: str, actor: str, conversation_id: str | None = None) -> None:
    session.add(ChangeLog(entity_type=entity_type, entity_id=entity_id, customer_id=customer_id, field=field,
                          old_value=_s(old), new_value=_s(new), source=source, actor=actor, conversation_id=conversation_id))


# ------------------------------------------------------------------ read tools (agent)
def profile_snapshot(c: Customer) -> dict:
    return {"customer_id": c.customer_id, "full_name": c.full_name, "email": c.email, "mobile_number": c.mobile_number,
            "preferred_language": c.preferred_language, "address": c.address or {}, "status": c.status}


async def get_profile_details(customer_id: str) -> dict:
    """The verified customer's own details (mobile is masked when read aloud)."""
    async with get_sessionmaker()() as s:
        c = await resolve_customer(s, customer_id)
        snap = profile_snapshot(c)
        return ok({**snap, "mobile_masked": mask_mobile(c.mobile_number), "address_text": v.format_address(c.address)})


async def check_order_address_edit(customer_id: str, order_id: str) -> dict:
    async with get_sessionmaker()() as s:
        try:
            o = await get_owned_order(s, customer_id, order_id)
        except NotFoundError:
            return fail("order_not_found", f"No order {order_id} was found on this account.")
        eligible = o.order_status in v.EDITABLE_ORDER_STATUSES
        return ok({"order_id": o.order_id, "order_status": o.order_status, "eligible": eligible,
                   "current_address": o.shipping_address, "current_address_text": v.format_address(o.shipping_address),
                   "reason": "The order has not been dispatched, so the delivery address can be changed." if eligible else
                             f"The delivery address can only be changed before dispatch; this order is already {o.order_status.replace('_', ' ')}."})


# ------------------------------------------------------------------ write helpers (shared)
async def _assert_unique(session: AsyncSession, customer: Customer, clean: dict) -> None:
    if "email" in clean:
        n = (await session.execute(select(func.count()).select_from(Customer).where(
            func.lower(Customer.email) == clean["email"].lower(), Customer.id != customer.id))).scalar_one()
        if n:
            raise ActionError("That email address is already used by another customer.", code="email_taken")
    if "mobile_number" in clean:
        n = (await session.execute(select(func.count()).select_from(Customer).where(
            Customer.mobile_number.like(f"%{clean['mobile_number'][-10:]}"), Customer.id != customer.id))).scalar_one()
        if n:
            raise ActionError("That mobile number is already used by another customer.", code="mobile_taken")


async def apply_profile_changes(session: AsyncSession, customer: Customer, changes: dict, *, source: str, actor: str,
                                conversation_id: str | None = None) -> dict:
    """Validate, check uniqueness, update the customer and write the change log. Does NOT commit."""
    clean, errors = v.validate_profile_changes(changes)
    if errors:
        raise ValidationFailed("; ".join(f"{k}: {m}" for k, m in errors.items()))
    diff = v.diff_changes(profile_snapshot(customer), clean)
    if not diff:
        return {"changed": {}, "message": "Nothing to change."}
    await _assert_unique(session, customer, diff)
    applied: dict = {}
    for field, new in diff.items():
        if field == "address":
            old = dict(customer.address or {})
            merged = v.merge_address(old, new)
            customer.address = merged                      # reassign so the JSON change is detected
            applied[field] = {"old": old, "new": merged}
        else:
            old = getattr(customer, field)
            setattr(customer, field, new)
            applied[field] = {"old": old, "new": new}
        log_change(session, entity_type="customer", entity_id=customer.customer_id, customer_id=customer.customer_id,
                   field=field, old=applied[field]["old"], new=applied[field]["new"], source=source, actor=actor,
                   conversation_id=conversation_id)
    return {"changed": applied}


async def apply_order_address(session: AsyncSession, customer_id: str, order_id: str, address: dict, *, source: str,
                              actor: str, conversation_id: str | None = None) -> dict:
    """Edit an order's delivery address (only placed/processing, only the owner's order). Does NOT commit."""
    order = await get_owned_order(session, customer_id, order_id)
    if order.order_status not in v.EDITABLE_ORDER_STATUSES:
        raise ActionError(f"The delivery address can only be changed before dispatch; this order is already "
                          f"{order.order_status.replace('_', ' ')}.", code="order_not_editable")
    clean, errs = v.validate_address(address, partial_ok=True)
    if errs:
        raise ValidationFailed("; ".join(f"{k}: {m}" for k, m in errs.items()))
    old = dict(order.shipping_address or {})
    merged = v.merge_address(old, clean)
    if all((merged.get(k) or None) == (old.get(k) or None) for k in v.ADDRESS_FIELDS):
        return {"order_id": order.order_id, "changed": False, "message": "Nothing to change."}
    order.shipping_address = merged
    log_change(session, entity_type="order", entity_id=order.order_id, customer_id=customer_id, field="shipping_address",
               old=old, new=merged, source=source, actor=actor, conversation_id=conversation_id)
    return {"order_id": order.order_id, "changed": True, "old_address": old, "new_address": merged,
            "new_address_text": v.format_address(merged)}


# ------------------------------------------------------------------ confirmed-action executors
async def revalidate_update_profile(session: AsyncSession, customer_id: str, params: dict) -> rules.RuleResult:
    c = await resolve_customer(session, customer_id)
    clean, errors = v.validate_profile_changes(params.get("changes"))
    if errors:
        return rules.RuleResult(False, "invalid", "; ".join(errors.values()))
    try:
        await _assert_unique(session, c, v.diff_changes(profile_snapshot(c), clean))
    except ActionError as exc:
        return rules.RuleResult(False, exc.code, exc.message)
    return rules.RuleResult(True, "eligible", "ok")


async def execute_update_profile(session: AsyncSession, customer_id: str, params: dict, conversation_id: str | None) -> dict:
    c = await resolve_customer(session, customer_id)
    res = await apply_profile_changes(session, c, params["changes"], source="voice_agent",
                                      actor=f"agent:{(conversation_id or '')[:8]}", conversation_id=conversation_id)
    return {"changes": {k: {"old": _speak(k, x["old"]), "new": _speak(k, x["new"])} for k, x in res["changed"].items()}}


def _speak(field: str, value):
    return v.format_address(value) if field == "address" and isinstance(value, dict) else value


async def revalidate_order_address(session: AsyncSession, customer_id: str, params: dict) -> rules.RuleResult:
    o = await get_owned_order(session, customer_id, params["order_id"])
    if o.order_status not in v.EDITABLE_ORDER_STATUSES:
        return rules.RuleResult(False, "order_not_editable",
                                f"The delivery address can only be changed before dispatch; this order is already {o.order_status.replace('_', ' ')}.")
    _, errs = v.validate_address(params.get("address"), partial_ok=True)
    return rules.RuleResult(not errs, "invalid" if errs else "eligible", "; ".join(errs.values()) or "ok")


async def execute_order_address(session: AsyncSession, customer_id: str, params: dict, conversation_id: str | None) -> dict:
    res = await apply_order_address(session, customer_id, params["order_id"], params["address"], source="voice_agent",
                                    actor=f"agent:{(conversation_id or '')[:8]}", conversation_id=conversation_id)
    return {"order_id": res["order_id"], "new_address": res.get("new_address_text"), "changes": {"delivery_address": {
        "old": v.format_address(res.get("old_address")), "new": res.get("new_address_text")}}}

