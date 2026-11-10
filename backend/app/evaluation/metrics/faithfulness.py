"""Faithfulness: nothing in the answer contradicts or goes beyond the retrieved evidence."""
from __future__ import annotations

from app.guardrails.hallucination_check import check_grounding


def faithfulness(response: str, evidence: object, user_text: str = "") -> dict:
    rep = check_grounding(response, evidence, extra_allowed=[user_text])
    n = len(rep.unsupported_ids) + len(rep.unsupported_amounts) + len(rep.unsupported_dates)
    return {"score": 5.0 if rep.passed else max(1.0, 5.0 - 2 * n), "passed": rep.passed,
            "detail": "ok" if rep.passed else rep.to_result().details}
