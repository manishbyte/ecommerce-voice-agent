"""Output guardrail: every factual claim must be supported by retrieved evidence.

Checks (deterministic): identifiers, money amounts, calendar dates, catalogue product names and
other customers' names. Pure Python.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.guardrails import GuardrailResult
from app.utils.formatting import normalize_digits
from app.utils.identifiers import ANY_ID_RE

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"])}
_MON_ALT = "|".join(sorted(list(_MONTHS) + [m[:3] for m in _MONTHS], key=len, reverse=True))
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MON_ALT})\b(?:,?\s+(\d{{4}}))?", re.I)
_MDY = re.compile(rf"\b({_MON_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?", re.I)
_MONEY = re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:rupees?|rs\b|रुपये|रुपए|ரூபாய்|రూపాయలు)", re.I)


def _mon(name: str) -> int:
    n = name.lower()
    return _MONTHS.get(n) or next(v for k, v in _MONTHS.items() if k.startswith(n[:3]))


def _dec(s: str) -> Decimal | None:
    try:
        return Decimal(s.replace(",", "")).normalize()
    except InvalidOperation:
        return None


@dataclass
class Evidence:
    ids: set[str] = field(default_factory=set)
    amounts: set[Decimal] = field(default_factory=set)
    dates: set[tuple[int, int]] = field(default_factory=set)       # (month, day)
    full_dates: set[tuple[int, int, int]] = field(default_factory=set)
    text: str = ""


def build_evidence(evidence: object, extra_allowed: list[str] | None = None) -> Evidence:
    ev = Evidence()
    blob = json.dumps(evidence, default=str, ensure_ascii=False)
    blob_n = normalize_digits(blob + " " + " ".join(extra_allowed or []))
    ev.text = blob_n.lower()
    ev.ids = {m.group(0).upper() for m in ANY_ID_RE.finditer(blob_n)}

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float, Decimal)):
            d = _dec(str(x))
            if d is not None:
                ev.amounts.add(d)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple, set)):
            for v in x:
                walk(v)
        elif isinstance(x, str):
            for m in re.finditer(r"(?<![\w-])\d[\d,]*(?:\.\d+)?(?![\w-])", x):
                d = _dec(m.group(0))
                if d is not None:
                    ev.amounts.add(d)
    walk(evidence)
    for m in _ISO.finditer(blob_n):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        ev.dates.add((mo, d))
        ev.full_dates.add((y, mo, d))
    return ev


@dataclass
class HallucinationReport:
    passed: bool
    unsupported_ids: list[str] = field(default_factory=list)
    unsupported_amounts: list[str] = field(default_factory=list)
    unsupported_dates: list[str] = field(default_factory=list)
    unsupported_names: list[str] = field(default_factory=list)

    def to_result(self) -> GuardrailResult:
        if self.passed:
            return GuardrailResult()
        return GuardrailResult(False, "unsupported_claims", "Response contains claims not found in the records.",
                               {k: v for k, v in self.__dict__.items() if k != "passed" and v})


def check_grounding(response: str, evidence: object, *, catalogue_names: list[str] | None = None,
                    foreign_names: list[str] | None = None, extra_allowed: list[str] | None = None) -> HallucinationReport:
    ev = build_evidence(evidence, extra_allowed)
    text = normalize_digits(response or "")
    rep = HallucinationReport(True)

    for m in ANY_ID_RE.finditer(text):
        v = m.group(0).upper()
        if v not in ev.ids and v not in rep.unsupported_ids:
            rep.unsupported_ids.append(v)

    for m in _MONEY.finditer(text):
        raw = m.group(1) or m.group(2)
        d = _dec(raw)
        shown = format(d, 'f') if d is not None else raw
        if d is not None and d not in ev.amounts and shown not in rep.unsupported_amounts:
            rep.unsupported_amounts.append(shown)

    seen: set[str] = set()
    for m in _ISO.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if (y, mo, d) not in ev.full_dates and m.group(0) not in seen:
            seen.add(m.group(0)); rep.unsupported_dates.append(m.group(0))
    for m in _DMY.finditer(text):
        mo, d = _mon(m.group(2)), int(m.group(1))
        if (mo, d) not in ev.dates and m.group(0) not in seen:
            seen.add(m.group(0)); rep.unsupported_dates.append(m.group(0).strip())
    for m in _MDY.finditer(text):
        mo, d = _mon(m.group(1)), int(m.group(2))
        if (mo, d) not in ev.dates and m.group(0) not in seen:
            seen.add(m.group(0)); rep.unsupported_dates.append(m.group(0).strip())

    low = text.lower()
    for name in catalogue_names or []:
        if len(name) > 4 and name.lower() in low and name.lower() not in ev.text:
            rep.unsupported_names.append(name)
    for name in foreign_names or []:
        if len(name) > 4 and name.lower() in low and name.lower() not in ev.text:
            rep.unsupported_names.append(name)

    rep.passed = not (rep.unsupported_ids or rep.unsupported_amounts or rep.unsupported_dates or rep.unsupported_names)
    return rep


def extract_dates(text: str) -> set[tuple[int, int]]:
    """All (month, day) pairs mentioned in a text, in ISO or natural-language form."""
    t = normalize_digits(text or "")
    out = {(int(m.group(2)), int(m.group(3))) for m in _ISO.finditer(t)}
    out |= {(_mon(m.group(2)), int(m.group(1))) for m in _DMY.finditer(t)}
    out |= {(_mon(m.group(1)), int(m.group(2))) for m in _MDY.finditer(t)}
    return out
