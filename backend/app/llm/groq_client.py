"""Single, shared Groq (LangChain) configuration used by every agent."""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.core.exceptions import ProviderUnavailable
from app.llm.model_config import ROLES, model_for


def llm_available() -> bool:
    return bool(get_settings().groq_api_key)


@lru_cache(maxsize=16)
def _build(model: str, temperature: float, max_tokens: int):
    from langchain_groq import ChatGroq

    s = get_settings()
    return ChatGroq(model=model, api_key=s.groq_api_key, temperature=temperature, max_tokens=max_tokens,
                    timeout=s.llm_timeout_seconds, max_retries=2)


def get_llm(role: str = "response"):
    if not llm_available():
        raise ProviderUnavailable("GROQ_API_KEY is not configured", code="llm_unavailable")
    cfg = ROLES[role]
    return _build(model_for(role), cfg.temperature, cfg.max_tokens)
