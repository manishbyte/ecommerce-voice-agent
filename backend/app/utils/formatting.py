"""Formatting helpers (no third-party imports)."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal

_MD_RE = re.compile(r"[*_`#>|~]+")
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def money(value) -> str:
    v = Decimal(str(value))
    return f"₹{v:,.0f}" if v == v.to_integral() else f"₹{v:,.2f}"


def iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, (date, datetime)) else str(value)


def num(value):
    """Decimal -> int/float for JSON."""
    if value is None:
        return None
    d = Decimal(str(value))
    return int(d) if d == d.to_integral() else float(d)


def clean_for_speech(text: str) -> str:
    text = _MD_RE.sub("", text or "")
    text = _EMOJI_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_digits(text: str) -> str:
    """Convert any Unicode decimal digits (Devanagari, Tamil, ...) to ASCII."""
    out = []
    for ch in text or "":
        if ch.isdigit() and not ch.isascii():
            try:
                out.append(str(unicodedata.digit(ch)))
                continue
            except ValueError:
                pass
        out.append(ch)
    return "".join(out)
