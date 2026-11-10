"""Language Agent: greeting, language selection, explicit language changes."""
from __future__ import annotations

import logging
import uuid
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import update

from app.agents.prompts import LANGUAGE_SYSTEM
from app.agents.state import AgentState
from app.core.logging import emit_event
from app.database.connection import get_sessionmaker
from app.llm.groq_client import llm_available
from app.llm.structured_output import structured_invoke
from app.models import Conversation
from app.voice.language_config import GREETING, LANGUAGE_REPROMPT, LANGUAGES, get_language
from app.voice.language_detection import detect_language_change_request, detect_language_preference

log = logging.getLogger(__name__)


class LanguagePick(BaseModel):
    language: Literal["english", "hindi", "marathi", "hinglish", "tamil", "telugu", "kannada", "malayalam",
                      "bengali", "gujarati", "punjabi", "unknown"]


async def _save_language(conversation_id: str, key: str) -> None:
    async with get_sessionmaker()() as s:
        async with s.begin():
            await s.execute(update(Conversation).where(Conversation.id == uuid.UUID(conversation_id))
                            .values(selected_language=key))


async def _interpret(msg: str) -> str | None:
    key = detect_language_preference(msg)
    if key or not llm_available():
        return key
    try:  # LLM fallback for phrasing the rules don't cover
        pick = await structured_invoke(LanguagePick, [("system", LANGUAGE_SYSTEM), ("human", msg)], role="language")
        return pick.language if pick.language in LANGUAGES else None
    except Exception as exc:  # noqa: BLE001
        log.info("language LLM fallback unavailable: %s", exc)
        return None


def needs_language_node(state: AgentState) -> bool:
    if not state.get("language_initialized"):
        return True
    return detect_language_change_request(state.get("current_user_message", ""), state.get("selected_language")) is not None


async def language_node(state: AgentState) -> dict:
    conv = state["conversation_id"]
    msg = (state.get("current_user_message") or "").strip()

    if not state.get("language_initialized"):
        if not msg:   # very first turn of a new conversation
            await emit_event(conv, "language_selection_started", agent="language", summary="Asking preferred language")
            return {"response": GREETING, "current_intent": "language_selection", "active_agent": "language"}
        key = await _interpret(msg)
        if key is None:
            await emit_event(conv, "language_selection_started", agent="language", status="retry",
                             summary="Language not understood, re-asking")
            return {"response": LANGUAGE_REPROMPT, "current_intent": "language_selection", "active_agent": "language"}
        await _save_language(conv, key)
        await emit_event(conv, "language_selected", agent="language", summary=f"Language set to {key}",
                         data={"language": key})
        update_ = {"selected_language": key, "language_initialized": True, "language_changed": True,
                   "current_intent": "language_selection", "active_agent": "language"}
        if state.get("customer_verified"):
            update_["response"] = get_language(key).confirmation
        else:  # identity still needed -> let the response agent ask for the mobile number in this language
            update_["notices"] = [{"type": "ask_mobile"}]
        return update_

    key = detect_language_change_request(msg, state.get("selected_language"))
    if key:
        await _save_language(conv, key)
        await emit_event(conv, "language_changed", agent="language", summary=f"Language changed to {key}",
                         data={"language": key})
        return {"selected_language": key, "language_changed": True, "current_intent": "language_selection",
                "response": get_language(key).confirmation, "active_agent": "language"}
    return {}
