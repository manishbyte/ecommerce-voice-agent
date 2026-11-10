"""Heuristic prompt-injection / data-exfiltration detection. Pure Python.

This is a *defence in depth* layer only. Real protection comes from backend authorization
(customer_authorization.py): even a successful injection cannot read another customer's data.
"""
from __future__ import annotations

import re

from app.guardrails import GuardrailResult

_INJECTION = [
    r"ignore (all |any |the )?(previous|prior|above|earlier|your) (instructions|rules|prompts?|guidelines)",
    r"disregard (all |any |the )?(previous|prior|above|your) ",
    r"forget (everything|all|your) (instructions|rules|above|previous)",
    r"(reveal|show|print|repeat|display|tell me) (me )?(your|the) (system |hidden |initial )?(prompt|instructions|rules)",
    r"you are now (a|an|in)\b", r"\bact as (a|an|if)\b", r"pretend (to be|you are)",
    r"developer mode", r"\bjailbreak\b", r"\bdan mode\b", r"override (your|the|all) (rules|policy|policies|safety)",
    r"new (instructions|rules) *:", r"</?(system|assistant|instructions?)>", r"\[\s*system\s*\]",
    r"(pichle|purane|saare) (instructions|nirdesh).{0,20}(ignore|bhool)", r"system prompt",
]
_EXFIL = [
    r"(all|every|other|another|someone else'?s?|everyone'?s?) (the )?customers?('s)? (data|details|orders|records|information|numbers?)",
    r"list (all|every) (customers?|orders|users|mobile|emails?)",
    r"(dump|export|download) (the )?(database|db|table|customers)",
    r"\b(select|insert|update|delete|drop|alter|truncate)\b.{0,40}\b(from|into|table|set|where)\b",
    r";\s*--", r"\bunion\s+select\b",
    r"(mere|meri) (pados|dost|friend|neighbou?r)\w* (ka|ki|ke) (order|number|details)",
]
_UNSAFE_ACTION = [
    r"(refund|cancel|return)\b.{0,40}\b(without|skip|bypass|no) (confirmation|verification|checking|asking)",
    r"(don'?t|do not|no need to) (ask|confirm|verify)",
    r"(auto|automatically) (approve|refund|confirm)",
    r"(give|issue) (me )?(a )?(full |double |extra )?refund (anyway|regardless|now)",
]

_INJ_RE = [re.compile(p, re.I) for p in _INJECTION]
_EXF_RE = [re.compile(p, re.I) for p in _EXFIL]
_ACT_RE = [re.compile(p, re.I) for p in _UNSAFE_ACTION]

REFUSAL = ("I can only help with your own orders, payments, refunds and support requests, "
           "and I can't follow instructions that change how I work. How can I help with your account?")


def detect_prompt_injection(text: str) -> GuardrailResult:
    t = text or ""
    for category, rx_list in (("prompt_injection", _INJ_RE), ("data_exfiltration", _EXF_RE),
                              ("unsafe_action", _ACT_RE)):
        for rx in rx_list:
            if rx.search(t):
                return GuardrailResult(False, category, REFUSAL, {"pattern": rx.pattern[:60]})
    return GuardrailResult()
