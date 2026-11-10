from __future__ import annotations


def relevance(case: dict, actual_intent: str | None, response: str) -> dict:
    if not response:
        return {"score": 1.0, "passed": False, "detail": "empty response"}
    exp = case.get("expected_intent")
    if not exp:
        return {"score": 5.0, "passed": True, "detail": "no intent expectation"}
    ok = exp == actual_intent
    return {"score": 5.0 if ok else 2.0, "passed": ok, "detail": f"expected {exp}, got {actual_intent}"}
