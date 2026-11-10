"""Data-protection helpers. This is NOT an authentication module (the demo has no login)."""
from __future__ import annotations

import re

_SECRET_RE = re.compile(r"(gsk_[A-Za-z0-9]{10,}|sk-[A-Za-z0-9]{10,}|api[_-]?key\s*[:=]\s*\S+)", re.I)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_mobile(value: str) -> str | None:
    """Return the last 10 digits of an Indian mobile number, or None."""
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if len(digits) >= 10 else None


def mask_mobile(value: str) -> str:
    d = re.sub(r"\D", "", value or "")
    return f"******{d[-4:]}" if len(d) >= 4 else "****"


def redact_secrets(text: str) -> str:
    return _SECRET_RE.sub("[redacted]", text or "")


def strip_control_chars(text: str) -> str:
    return _CTRL_RE.sub("", text or "")


def sanitize_for_log(text: str, limit: int = 200) -> str:
    return redact_secrets(strip_control_chars(text))[:limit]
