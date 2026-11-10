"""Output guardrail: final-response validation (non-empty, length, leakage, language). Pure Python."""
from __future__ import annotations

import re

from app.core.security import redact_secrets
from app.guardrails import GuardrailResult
from app.voice.language_config import SCRIPT_RANGES, get_language

_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LEAK = re.compile(r"(system prompt|my instructions are|as an ai language model|<\s*/?\s*system\s*>)", re.I)


def script_ratio(text: str, script: str) -> float:
    """Share of alphabetic characters that belong to the given script."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 1.0
    if script == "latin":
        return sum(1 for c in letters if c.isascii()) / len(letters)
    lo, hi = SCRIPT_RANGES[script]
    return sum(1 for c in letters if lo <= ord(c) <= hi) / len(letters)


def validate_output(response: str | None, *, language_key: str | None, own_mobile: str | None = None,
                    own_email: str | None = None, max_chars: int = 700,
                    allowed_numbers: list[str] | None = None) -> GuardrailResult:
    text = (response or "").strip()
    if not text:
        return GuardrailResult(False, "empty_response", "empty response")
    if len(text) > max_chars:
        return GuardrailResult(False, "too_long", "response too long for a voice reply", {"length": len(text)})
    if redact_secrets(text) != text:
        return GuardrailResult(False, "secret_leak", "response contains a secret-like token")
    if _LEAK.search(text):
        return GuardrailResult(False, "prompt_leak", "response discloses internal instructions")

    own_digits = re.sub(r"\D", "", own_mobile or "")[-10:]
    allowed = {re.sub(r"\D", "", n)[-10:] for n in (allowed_numbers or [])} | {own_digits}
    for m in _PHONE.finditer(text):
        if re.sub(r"\D", "", m.group(0))[-10:] not in allowed:
            return GuardrailResult(False, "foreign_contact_detail", "response contains another phone number")
    for m in _EMAIL.finditer(text):
        if own_email and m.group(0).lower() != own_email.lower():
            return GuardrailResult(False, "foreign_contact_detail", "response contains another email address")

    cfg = get_language(language_key)
    if cfg and cfg.script != "latin" and script_ratio(text, cfg.script) < 0.5:
        return GuardrailResult(False, "language_mismatch", f"response is not written in {cfg.name}",
                               {"script_ratio": round(script_ratio(text, cfg.script), 2)})
    if cfg and cfg.script == "latin" and script_ratio(text, "latin") < 0.8:
        return GuardrailResult(False, "language_mismatch", f"response is not written in {cfg.name}")
    return GuardrailResult()
