"""Pure business rules. Backend code - not LLM instructions - decides eligibility.

No third-party imports, so these are unit-testable anywhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

CANCELLABLE_STATUSES = {"placed", "processing"}
RETURNABLE_STATUSES = {"delivered"}
REFUNDABLE_ORDER_STATUSES = {"cancelled", "returned"}
OPEN_TICKET_STATUSES = {"open", "in_progress"}
REFUND_SLA_DAYS = 7

TICKET_CATEGORIES = {
    "delivery_delay", "damaged_item", "wrong_item", "missing_item", "payment_issue",
    "cancellation_refund", "refund_status", "return_request", "replacement_request",
    "warranty_query", "address_change", "product_question", "delivery_query",
    "invoice_request", "complaint", "human_escalation",
}
ACTION_TYPES = {"cancel_order", "request_refund", "create_ticket", "update_profile", "update_order_address"}
INACTIVE_STATUS = "inactive"
ORDER_STATUSES = {"placed", "processing", "shipped", "delayed", "delivered", "cancelled", "returned", "payment_failed"}
PAYMENT_STATUSES = {"pending", "captured", "failed", "refunded"}
REFUND_STATUSES = {"requested", "processing", "approved", "completed", "rejected"}
TICKET_STATUSES = {"open", "in_progress", "resolved", "closed"}


@dataclass(frozen=True)
class RuleResult:
    eligible: bool
    code: str
    message: str


def check_cancellation(order_status: str) -> RuleResult:
    if order_status in CANCELLABLE_STATUSES:
        return RuleResult(True, "eligible", "Order has not been dispatched, so it can be cancelled.")
    reasons = {
        "shipped": "The order has already been shipped.",
        "delayed": "The order has already been shipped (delivery is delayed).",
        "delivered": "The order has already been delivered; a return can be requested instead.",
        "cancelled": "The order is already cancelled.",
        "returned": "The order has already been returned.",
        "payment_failed": "The order was never placed because payment failed.",
    }
    return RuleResult(False, "not_cancellable", reasons.get(order_status, f"Orders in status '{order_status}' cannot be cancelled."))


def check_return(order_status: str, delivered_at: date | None, today: date, window_days: int) -> RuleResult:
    if order_status not in RETURNABLE_STATUSES or delivered_at is None:
        return RuleResult(False, "not_delivered", "Only delivered orders can be returned or replaced.")
    deadline = delivered_at + timedelta(days=window_days)
    if today > deadline:
        return RuleResult(False, "window_expired", f"The {window_days}-day return window ended on {deadline.isoformat()}.")
    return RuleResult(True, "eligible", f"Within the {window_days}-day window (until {deadline.isoformat()}).")


def check_refund(order_status: str, payment_status: str | None, existing_refund_statuses: list[str]) -> RuleResult:
    if payment_status != "captured":
        return RuleResult(False, "no_captured_payment", "No captured payment exists for this order, so there is nothing to refund.")
    if existing_refund_statuses:
        return RuleResult(False, "refund_exists", "A refund already exists for this payment.")
    if order_status not in REFUNDABLE_ORDER_STATUSES:
        return RuleResult(False, "order_not_refundable",
                          "Refunds are only started for cancelled or returned orders. For a delivered order, a return must be raised first.")
    return RuleResult(True, "eligible", "Order is cancelled/returned with a captured payment and no existing refund.")


def refund_estimated_completion(today: date) -> date:
    return today + timedelta(days=REFUND_SLA_DAYS)


def explain_payment(payment_status: str, order_status: str) -> str:
    if payment_status == "failed":
        if order_status == "payment_failed":
            return "The payment attempt failed, so per our records no amount was captured and the order was not placed."
        return "The payment attempt failed and no amount was captured."
    if payment_status == "captured":
        return "The payment was captured successfully."
    return f"The payment status is '{payment_status}'."
