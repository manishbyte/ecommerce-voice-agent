"""Groundedness: share of identifiers in the answer that exist in the evidence."""
from __future__ import annotations

import json

from app.utils.identifiers import ANY_ID_RE


def groundedness(response: str, evidence: object, user_text: str = "") -> dict:
    ids = {m.group(0).upper() for m in ANY_ID_RE.finditer(response or "")}
    if not ids:
        return {"score": 5.0, "passed": True, "detail": "no identifiers claimed"}
    blob = (json.dumps(evidence, default=str, ensure_ascii=False) + " " + user_text).upper()
    grounded = {i for i in ids if i in blob}
    ratio = len(grounded) / len(ids)
    return {"score": round(1 + 4 * ratio, 2), "passed": ratio == 1.0, "detail": f"ungrounded: {sorted(ids - grounded)}" if ratio < 1 else "ok"}
