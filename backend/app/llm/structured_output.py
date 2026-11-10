"""Schema-constrained LLM calls (Pydantic) with one retry."""
from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel

from app.core.exceptions import ProviderUnavailable
from app.llm.groq_client import get_llm

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


async def structured_invoke(schema: type[T], messages: list, role: str = "supervisor", attempts: int = 2) -> T:
    llm = get_llm(role).with_structured_output(schema)
    last: Exception | None = None
    for _ in range(attempts):
        try:
            out = await llm.ainvoke(messages)
            if isinstance(out, schema):
                return out
            return schema.model_validate(out)
        except Exception as exc:  # noqa: BLE001
            last = exc
            log.warning("structured call failed (%s): %s", schema.__name__, exc)
    raise ProviderUnavailable(f"structured output failed: {last}", code="llm_error")


async def text_invoke(messages: list, role: str = "response") -> str:
    out = await get_llm(role).ainvoke(messages)
    return (out.content if isinstance(out.content, str) else str(out.content)).strip()
