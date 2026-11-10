"""Input guardrail: shape/length validation and control-character stripping. Pure Python."""
from __future__ import annotations

import re

from app.core.security import strip_control_chars
from app.guardrails import GuardrailResult
from app.utils.identifiers import CUSTOMER_ID_RE, ORDER_ID_RE


def validate_user_input(text: str | None, max_chars: int = 1000) -> tuple[GuardrailResult, str]:
    """Return (result, sanitized_text)."""
    cleaned = re.sub(r"\s+", " ", strip_control_chars(text or "")).strip()
    if not cleaned:
        return GuardrailResult(False, "empty_input", "I didn't catch that. Could you please say it again?"), ""
    if len(cleaned) > max_chars:
        return (GuardrailResult(False, "input_too_long", "That message is too long. Could you shorten it?",
                                {"length": len(cleaned)}), cleaned[:max_chars])
    return GuardrailResult(), cleaned


def validate_identifier(value: str | None, kind: str) -> bool:
    pattern = {"customer": CUSTOMER_ID_RE, "order": ORDER_ID_RE}[kind]
    return bool(value and pattern.match(value))
