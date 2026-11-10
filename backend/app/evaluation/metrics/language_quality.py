"""Language consistency (script-based, deterministic)."""
from __future__ import annotations

import re

from app.guardrails.output_validation import script_ratio
from app.voice.language_config import get_language

_STRIP = re.compile(r"(?:CUS|ORD|PRD|PAY|REF|TKT|TXN|TRK)\d+|₹\s?[\d,\.]+|\d+")


def language_quality(language_key: str, response: str) -> dict:
    cfg = get_language(language_key)
    if cfg is None:
        return {"score": 5.0, "passed": True, "detail": "unknown language"}
    text = _STRIP.sub("", response or "")
    ratio = script_ratio(text, cfg.script)
    threshold = 0.7 if cfg.script != "latin" else 0.9
    return {"score": round(1 + 4 * min(1.0, ratio / threshold), 2), "passed": ratio >= threshold,
            "detail": f"{cfg.script} ratio {ratio:.2f}"}
