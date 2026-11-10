"""Hallucination flag: unsupported claims OR a forbidden claim appearing in the answer."""
from __future__ import annotations

from app.evaluation.metrics.correctness import forbidden_hits
from app.guardrails.hallucination_check import check_grounding


def hallucination(case: dict, response: str, evidence: object, user_text: str = "") -> dict:
    rep = check_grounding(response, evidence, extra_allowed=[user_text])
    hits = forbidden_hits(response, case.get("forbidden_claims") or [])
    flagged = (not rep.passed) or bool(hits)
    return {"flagged": flagged, "unsupported": rep.to_result().details if not rep.passed else {}, "forbidden": hits}
