"""Intent -> specialist routing and conditional-edge helpers."""
from __future__ import annotations

INTENTS = [
    "language_selection", "order_tracking", "order_cancellation", "product_information", "payment_status",
    "refund_status", "refund_request", "complaint", "return_request", "replacement_request", "warranty_issue",
    "general_support", "identity_verification", "clarification_required", "human_escalation",
    "action_confirmation","end_conversation",
    "profile_info", "profile_update", "order_address_update",
]

SPECIALISTS = ["order", "product", "payment", "refund", "complaint", "profile"]

INTENT_AGENTS: dict[str, list[str]] = {
    "order_tracking": ["order"], "order_cancellation": ["order"], "product_information": ["product"],
    "payment_status": ["payment"], "refund_status": ["refund"], "refund_request": ["refund"],
    "complaint": ["complaint"], "return_request": ["complaint"], "replacement_request": ["complaint"],
    "warranty_issue": ["complaint"], "human_escalation": ["complaint"],
    "general_support": [], "clarification_required": [], "identity_verification": [], "language_selection": [],
    "action_confirmation": [],
    "profile_info": ["profile"], "profile_update": ["profile"], "order_address_update": ["profile"],
}
MAX_AGENTS_PER_TURN = 3


def plan_agents(intent: str, suggested: list[str] | None) -> list[str]:
    """Primary agent(s) for the intent first, then any extra specialists the supervisor asked for."""
    queue = list(INTENT_AGENTS.get(intent, []))
    for a in suggested or []:
        if a in SPECIALISTS and a not in queue and queue:   # extras only when the intent already needs agents
            queue.append(a)
    return queue[:MAX_AGENTS_PER_TURN]


def next_agent(state: dict) -> str:
    """Conditional edge after the supervisor / each specialist."""
    if state.get("error_state") and not state.get("agent_queue"):
        return "validate_results"
    done = set(state.get("completed_agents", []))
    for a in state.get("agent_queue", []):
        if a not in done:
            return f"{a}_agent"
    return "validate_results"
