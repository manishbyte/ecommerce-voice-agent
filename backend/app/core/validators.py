"""Input validation + rule-based extraction for profile / address edits. Pure Python (no third-party imports).

Used by the dashboard API, the voice agent (profile_agent) and the confirmed-action executors, so the same
rules apply everywhere. Each validator returns (clean_value, error_message_or_None).
"""
from __future__ import annotations

import re

from app.core.security import normalize_mobile
from app.utils.formatting import normalize_digits
from app.voice.language_config import LANGUAGES, LOCALE_TO_KEY

PROFILE_FIELDS = ("full_name", "email", "mobile_number", "preferred_language", "address")
SENSITIVE_FIELDS = {"email", "mobile_number"}            # verification details: extra-explicit confirmation
ADDRESS_FIELDS = ("line1", "line2", "city", "state", "postal_code")
EDITABLE_ORDER_STATUSES = {"placed", "processing"}        # delivery address may only change before dispatch

_EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
_NAME = re.compile(r"^[^\W\d_][^\W\d_ .'\-]*([ .'\-]+[^\W\d_][^\W\d_ .'\-]*)*$", re.UNICODE)
_PIN = re.compile(r"^[1-9]\d{5}$")
_PLACE = re.compile(r"^[^\W\d_][\w .'\-]{1,59}$", re.UNICODE)
KEY_TO_LOCALE = {v: k for k, v in LOCALE_TO_KEY.items()}


def validate_name(v) -> tuple[str | None, str | None]:
    s = re.sub(r"\s+", " ", str(v or "")).strip()
    if not 2 <= len(s) <= 80 or not _NAME.match(s):
        return None, "Name must be 2-80 letters (spaces, . ' - allowed)."
    return s.title() if s.islower() else s, None


def validate_email(v) -> tuple[str | None, str | None]:
    s = str(v or "").strip().lower()
    if len(s) > 120 or not _EMAIL.match(s):
        return None, "Enter a valid email address (e.g. name@example.com)."
    return s, None


def validate_mobile(v) -> tuple[str | None, str | None]:
    """Accepts 10 digits with optional +91/0/spaces/dashes; stores '+91XXXXXXXXXX' like the seed data."""
    raw = normalize_digits(str(v or ""))
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        return None, "Mobile must be a valid 10-digit Indian number starting with 6-9."
    return f"+91{digits}", None


def validate_pin(v) -> tuple[str | None, str | None]:
    s = re.sub(r"\s", "", normalize_digits(str(v or "")))
    return (s, None) if _PIN.match(s) else (None, "PIN code must be exactly 6 digits (not starting with 0).")


def validate_language(v) -> tuple[str | None, str | None]:
    s = str(v or "").strip()
    if s in LOCALE_TO_KEY:
        return s, None
    key = s.lower()
    if key == "hinglish":
        return "hinglish", None
    if key in KEY_TO_LOCALE:
        return KEY_TO_LOCALE[key], None
    return None, f"Language must be one of: {', '.join(sorted(LANGUAGES))}."


def validate_address(a, *, partial_ok: bool = False) -> tuple[dict | None, dict]:
    """Return (clean_address, errors). `partial_ok` allows omitting fields (they keep their current value)."""
    a = dict(a or {})
    clean: dict = {}
    errors: dict = {}
    for f in ("line1", "city", "state"):
        v = re.sub(r"\s+", " ", str(a.get(f) or "")).strip()
        if not v:
            if not partial_ok:
                errors[f] = f"{f.replace('line1', 'address line 1')} is required."
            continue
        if f == "line1" and not 3 <= len(v) <= 120:
            errors[f] = "Address line 1 must be 3-120 characters."
        elif f != "line1" and not _PLACE.match(v):
            errors[f] = f"Enter a valid {f}."
        else:
            clean[f] = v
    l2 = re.sub(r"\s+", " ", str(a.get("line2") or "")).strip()
    if len(l2) > 120:
        errors["line2"] = "Address line 2 must be at most 120 characters."
    elif l2 or "line2" in a:
        clean["line2"] = l2 or None
    if a.get("postal_code") or not partial_ok:
        pin, err = validate_pin(a.get("postal_code"))
        if err:
            errors["postal_code"] = err
        else:
            clean["postal_code"] = pin
    return (None if errors else clean), errors


def validate_profile_changes(changes: dict | None) -> tuple[dict, dict]:
    """Validate any subset of profile fields. Returns (clean_changes, errors_by_field)."""
    clean: dict = {}
    errors: dict = {}
    c = {k: v for k, v in (changes or {}).items() if v not in (None, "", {})}
    for field, fn in (("full_name", validate_name), ("email", validate_email), ("mobile_number", validate_mobile),
                      ("preferred_language", validate_language)):
        if field in c:
            val, err = fn(c[field])
            if err:
                errors[field] = err
            else:
                clean[field] = val
    if "address" in c:
        addr, errs = validate_address(c["address"], partial_ok=True)
        if errs:
            errors["address"] = "; ".join(errs.values())
        else:
            clean["address"] = addr
    unknown = set(c) - set(PROFILE_FIELDS)
    for u in unknown:
        errors[u] = "This field cannot be edited."
    return clean, errors


def merge_address(current: dict | None, new: dict) -> dict:
    """New partial address over the current one (country is kept)."""
    out = dict(current or {})
    out.update({k: v for k, v in new.items() if k in ADDRESS_FIELDS or k == "country"})
    out.setdefault("country", "India")
    return out


def diff_changes(current: dict, clean: dict) -> dict:
    """Keep only fields whose value actually changes (address compared after merging)."""
    out: dict = {}
    for f, v in clean.items():
        if f == "address":
            merged = merge_address(current.get("address"), v)
            if any((merged.get(k) or None) != ((current.get("address") or {}).get(k) or None) for k in ADDRESS_FIELDS):
                out["address"] = v
        elif (current.get(f) or "") != v:
            out[f] = v
    return out


def format_address(a: dict | None) -> str:
    a = a or {}
    return ", ".join(x for x in [a.get("line1"), a.get("line2"), a.get("city"), a.get("state"), a.get("postal_code")] if x)


# ---------------------------------------------------------------------------------------------
# Rule-based extraction from a spoken/typed sentence (used when no LLM is available).
# ---------------------------------------------------------------------------------------------
_EMAIL_IN_TEXT = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_PIN_IN_TEXT = re.compile(r"(?<!\d)[1-9]\d{5}(?!\d)")
_TO = re.compile(r"\b(?:to|as|is|:)\s+(.+)$", re.I)


def parse_address_text(text: str) -> dict:
    """'12 MG Road, Pune, Maharashtra 411001' -> structured address (comma-separated input expected)."""
    t = normalize_digits(text or "").strip().strip(".")
    pin = (_PIN_IN_TEXT.findall(t) or [None])[-1]
    if pin:
        t = re.sub(rf"[\s,-]*{pin}\b", "", t)
    parts = [p.strip() for p in t.split(",") if p.strip()]
    out: dict = {}
    if pin:
        out["postal_code"] = pin
    if len(parts) >= 3:
        out.update({"line1": ", ".join(parts[:-2]), "city": parts[-2], "state": parts[-1]})
    elif len(parts) == 2:
        out.update({"line1": parts[0], "city": parts[1]})
    elif len(parts) == 1:
        out["line1"] = parts[0]
    return out


def parse_profile_changes(text: str, hint: str | None = None) -> dict:
    """Best-effort rule-based extraction. `hint` = the field the agent just asked about (follow-up turn)."""
    t = (text or "").strip()
    low = t.lower()
    out: dict = {}
    m = _EMAIL_IN_TEXT.search(t)
    if m:
        out["email"] = m.group(0)
    elif hint == "email":
        out["email"] = re.sub(r"\s*(at the rate|at)\s*", "@", re.sub(r"\s+dot\s+", ".", low)).replace(" ", "")
    digits = re.sub(r"\D", "", normalize_digits(t))
    if (hint == "mobile_number" or re.search(r"\b(mobile|phone|number|contact)\b", low)) and digits and "@" not in t:
        # short/odd numbers are passed on too, so the validator can explain what is wrong
        out["mobile_number"] = digits[-12:] if digits.startswith("91") and len(digits) >= 12 else (
            digits[-10:] if len(digits) >= 10 else digits)
    if re.search(r"\bname\b", low) or hint == "full_name":
        m = re.search(r"\bname\b.*?\b(?:to|as|is)\s+(.+)$", t, re.I) or (re.match(r"^(.+)$", t) if hint == "full_name" else None)
        if m:
            out["full_name"] = m.group(1).strip().strip(".")
    if re.search(r"\baddress\b", low) or hint == "address":
        m = _TO.search(t)
        body = m.group(1) if m and "address" in low else (t if hint == "address" else "")
        if body:
            addr = parse_address_text(body)
            if addr:
                out["address"] = addr
    return out


def pending_field_hint(changes_requested: list[str]) -> str | None:
    return changes_requested[0] if changes_requested else None


def mentioned_fields(text: str) -> list[str]:
    """Which profile fields the sentence talks about (to ask for the right new value)."""
    low = (text or "").lower()
    found = []
    for field, kws in (("address", ["address"]), ("email", ["email", "e-mail", "mail id"]),
                       ("mobile_number", ["mobile", "phone", "contact number", "my number"]), ("full_name", [" name"])):
        if any(k in f" {low}" for k in kws):
            found.append(field)
    return found
