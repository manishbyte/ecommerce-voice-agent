"""Controlled, typed, async tools. Agents never run arbitrary SQL."""
from __future__ import annotations


def ok(data=None, **extra) -> dict:
    return {"ok": True, "data": data, **extra}


def fail(code: str, message: str, **extra) -> dict:
    return {"ok": False, "error": code, "message": message, **extra}
