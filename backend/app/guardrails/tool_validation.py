"""Tool gateway: allow-list, argument validation, customer scoping, execution record + events.

Agents never call tool functions directly. They call `run_tool`, which
  * only permits registered tools,
  * validates arguments with strict Pydantic models (extra fields forbidden),
  * injects the *verified* customer id from graph state (the model/user cannot choose it),
  * records every execution for the monitor, the audit trail and the evaluation framework.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.logging import emit_event
from app.database.base import utcnow
from app.tools import fail

log = logging.getLogger(__name__)

ORDER_PATTERN = r"^ORD\d{4,}$"
PRODUCT_PATTERN = r"^PRD\d{4,}$"


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(_Args):
    pass


class OrderArgs(_Args):
    order_id: str = Field(pattern=ORDER_PATTERN)


class OptionalOrderArgs(_Args):
    order_id: str | None = Field(default=None, pattern=ORDER_PATTERN)


class LimitArgs(_Args):
    limit: int = Field(default=20, ge=1, le=50)


class QueryArgs(_Args):
    query: str = Field(min_length=2, max_length=120)


class ProductArgs(_Args):
    query: str | None = Field(default=None, max_length=120)
    product_id: str | None = Field(default=None, pattern=PRODUCT_PATTERN)

    @model_validator(mode="after")
    def _one_required(self):
        if not (self.query or self.product_id):
            raise ValueError("query or product_id required")
        return self


class TicketsArgs(_Args):
    order_id: str | None = Field(default=None, pattern=ORDER_PATTERN)
    only_open: bool = False


class MobileArgs(_Args):
    mobile: str = Field(min_length=10, max_length=20)


@dataclass(frozen=True)
class ToolSpec:
    fn: Callable
    args: type[_Args]
    needs_customer: bool = True


_REGISTRY: dict[str, ToolSpec] | None = None


def get_registry() -> dict[str, ToolSpec]:
    global _REGISTRY
    if _REGISTRY is None:
        from app.tools import customer_tools as c, order_tools as o, payment_tools as pay, product_tools as pr
        from app.tools import profile_tools as pf, refund_tools as r, ticket_tools as t

        _REGISTRY = {
            "get_customer_profile": ToolSpec(c.get_customer_profile, NoArgs),
            "find_customer_by_mobile": ToolSpec(c.find_customer_by_mobile, MobileArgs, needs_customer=False),
            "get_customer_orders": ToolSpec(o.get_customer_orders, LimitArgs),
            "get_order_details": ToolSpec(o.get_order_details, OrderArgs),
            "get_order_tracking": ToolSpec(o.get_order_tracking, OrderArgs),
            "find_orders_by_product": ToolSpec(o.find_orders_by_product, QueryArgs),
            "check_cancellation_eligibility": ToolSpec(o.check_cancellation_eligibility, OrderArgs),
            "get_product_details": ToolSpec(pr.get_product_details, ProductArgs, needs_customer=False),
            "check_product_availability": ToolSpec(pr.check_product_availability, ProductArgs, needs_customer=False),
            "get_payment_status": ToolSpec(pay.get_payment_status, OptionalOrderArgs),
            "get_payment_history": ToolSpec(pay.get_payment_history, NoArgs),
            "get_refund_status": ToolSpec(r.get_refund_status, OptionalOrderArgs),
            "check_refund_eligibility": ToolSpec(r.check_refund_eligibility, OrderArgs),
            "get_customer_tickets": ToolSpec(t.get_customer_tickets, TicketsArgs),
            "check_return_eligibility": ToolSpec(t.check_return_eligibility, OrderArgs),
            "get_profile_details": ToolSpec(pf.get_profile_details, NoArgs),
            "check_order_address_edit": ToolSpec(pf.check_order_address_edit, OrderArgs),
        }
    return _REGISTRY


def _summarize(result: dict) -> str:
    if not result.get("ok"):
        return f"failed: {result.get('error')}"
    d = result.get("data")
    if isinstance(d, list):
        return f"{len(d)} record(s)"
    if isinstance(d, dict):
        return "record found"
    return "ok"


async def run_tool(state: dict, name: str, **args) -> tuple[dict, dict]:
    """Validate and execute a tool. Returns (result, execution_record)."""
    conv = state.get("conversation_id")
    agent = state.get("active_agent")
    spec = get_registry().get(name)
    started = time.perf_counter()
    if spec is None:
        result = fail("tool_not_allowed", f"Tool '{name}' is not permitted.")
    else:
        try:
            parsed = spec.args(**args).model_dump(exclude_none=True)
        except ValidationError as exc:
            parsed = None
            result = fail("invalid_arguments", "; ".join(e["msg"] for e in exc.errors())[:200])
        if parsed is not None:
            if spec.needs_customer:
                cid = state.get("customer_id")
                if not (state.get("customer_verified") and cid):
                    parsed = None
                    result = fail("customer_not_verified", "Customer identity is not verified.")
                else:
                    parsed["customer_id"] = cid
            if parsed is not None:
                await emit_event(conv, "tool_called", agent=agent, summary=f"{name}", data={"tool": name, "args": {k: v for k, v in args.items()}})
                try:
                    result = await spec.fn(**parsed)
                except Exception as exc:  # noqa: BLE001
                    log.exception("tool %s crashed", name)
                    result = fail("tool_error", f"{type(exc).__name__}")
    latency = round((time.perf_counter() - started) * 1000)
    record = {"tool": name, "args": args, "ok": bool(result.get("ok")), "error": result.get("error"),
              "latency_ms": latency, "summary": _summarize(result), "agent": agent, "at": utcnow().isoformat()}
    await emit_event(conv, "tool_completed", agent=agent, status="ok" if record["ok"] else "error",
                     summary=f"{name}: {record['summary']}", data={"tool": name, "latency_ms": latency})
    return result, record
