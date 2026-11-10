from __future__ import annotations

from app.evaluation.metrics.correctness import fact_coverage


def completeness(case: dict, response: str) -> dict:
    cov, missing = fact_coverage(case, response)
    return {"score": round(1 + 4 * cov, 2), "passed": cov == 1.0, "detail": f"missing: {missing}" if missing else "all expected facts present"}
