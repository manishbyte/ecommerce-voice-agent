"""Blend deterministic + judge results and aggregate into a report summary. Pure Python."""
from __future__ import annotations

import statistics

from app.evaluation.evaluation_config import JUDGE_WEIGHT, METRICS, PASS_SCORE

JUDGE_KEYS = {"correctness", "faithfulness", "groundedness", "relevance", "completeness", "language_quality"}


def blend(det: float, judge: float | None) -> float:
    return round(det if judge is None else (1 - JUDGE_WEIGHT) * det + JUDGE_WEIGHT * judge, 2)


def case_scores(det: dict, judge: dict | None) -> dict:
    out = {}
    for m in METRICS:
        d = det[m]["score"]
        j = judge.get(m) if (judge and m in JUDGE_KEYS) else None
        out[m] = blend(d, j)
    return out


def case_passed(hard: dict, scores: dict, judge: dict | None) -> bool:
    if not all(hard.values()):                       # ownership, forbidden claims, action outcome, intent ...
        return False
    if judge and not judge.get("overall_pass", True):
        return False
    return all(scores[m] >= PASS_SCORE for m in ("correctness", "faithfulness", "groundedness", "completeness"))


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return round(s[min(len(s) - 1, int(round((p / 100) * (len(s) - 1))))], 1)


def summarize(results: list[dict]) -> dict:
    n = len(results)
    if not n:
        return {"cases": 0}
    avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else None
    metrics = {m: avg([r["scores"][m] for r in results]) for m in METRICS}
    lat = [t for r in results for t in r["latencies_ms"]]
    hard_keys = {k for r in results for k in r["hard_checks"]}
    hard = {k: round(sum(1 for r in results if r["hard_checks"].get(k, True)) / n, 3) for k in hard_keys}
    by_cat: dict[str, list[dict]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)
    return {
        "cases": n, "passed": sum(r["passed"] for r in results), "pass_rate": round(sum(r["passed"] for r in results) / n, 3),
        "overall_score": avg(list(metrics.values())), "metrics": metrics,
        "hallucination_rate": round(sum(1 for r in results if r["hallucination"]["flagged"]) / n, 3),
        "intent_accuracy": hard.get("intent"), "tool_selection_accuracy": round(sum(r["tool"]["selection"] for r in results) / n, 3),
        "tool_execution_accuracy": round(sum(r["tool"]["execution"] for r in results) / n, 3),
        "action_correctness": hard.get("action"), "ownership_isolation": hard.get("ownership"),
        "conversation_resolution": round(sum(1 for r in results if r["passed"]) / n, 3),
        "hard_checks": hard,
        "latency_ms": {"avg": round(statistics.mean(lat), 1) if lat else 0, "p50": _pct(lat, 50), "p95": _pct(lat, 95)},
        "by_category": {c: {"cases": len(v), "pass_rate": round(sum(x["passed"] for x in v) / len(v), 3)} for c, v in by_cat.items()},
        "judge_used": any(r["judge"] for r in results),
    }
