"""Tool selection / execution accuracy."""
from __future__ import annotations

PROFILE_TOOLS = {"get_customer_profile"}
EXPECTED_ERRORS = {"order_not_found", "refund_not_found", "payment_not_found", "product_not_found"}


def tool_accuracy(case: dict, tool_calls: list[dict]) -> dict:
    exp = case.get("expected_tool")
    names = [t["tool"] for t in tool_calls]
    data_tools = [t for t in tool_calls if t["tool"] not in PROFILE_TOOLS]
    if exp:
        selection = exp in names
    else:   # nothing customer-specific should be fetched
        selection = not data_tools
    bad = [t for t in tool_calls if not t["ok"] and t.get("error") not in EXPECTED_ERRORS]
    execution = not bad
    score = 1 + 2 * int(selection) + 2 * int(execution)
    return {"score": float(score), "selection": selection, "execution": execution, "passed": selection and execution,
            "detail": f"expected={exp} called={names} failed={[t['tool'] for t in bad]}"}
