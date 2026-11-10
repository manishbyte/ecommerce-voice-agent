"""Answer correctness: required facts present, forbidden claims absent (deterministic)."""
from __future__ import annotations

import re

from app.guardrails.hallucination_check import extract_dates
from app.utils.formatting import normalize_digits

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fact_present(response: str, fact: str) -> bool:
    text = normalize_digits(response or "")
    fact = str(fact)
    if _ISO.match(fact):
        return (int(fact[5:7]), int(fact[8:10])) in extract_dates(text)
    if fact.isdigit():                                  # amounts: compare without thousands separators
        return fact in re.sub(r"(?<=\d),(?=\d)", "", text)
    return fact.lower() in text.lower()


def forbidden_hits(response: str, forbidden: list[str]) -> list[str]:
    low = (response or "").lower()
    return [f for f in forbidden if f.lower() in low]


def fact_coverage(case: dict, response: str) -> tuple[float, list[str]]:
    facts = case.get("expected_facts") or []
    if not facts:
        return 1.0, []
    missing = [f for f in facts if not fact_present(response, f)]
    return (len(facts) - len(missing)) / len(facts), missing


def correctness(case: dict, response: str) -> dict:
    hits = forbidden_hits(response, case.get("forbidden_claims") or [])
    cov, missing = fact_coverage(case, response)
    if hits:
        return {"score": 1.0, "passed": False, "detail": f"forbidden claim(s) present: {hits}"}
    score = 1 + 4 * cov
    return {"score": round(score, 2), "passed": cov == 1.0 and bool(response), "detail": f"missing facts: {missing}" if missing else "ok"}
