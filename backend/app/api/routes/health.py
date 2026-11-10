from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.database.connection import ping
from app.dependencies import resources
from app.llm.groq_client import llm_available
from app.voice.stt import stt_available
from app.voice.tts import tts_available

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    db = await ping()
    s = get_settings()
    return {
        "status": "ok" if db and resources.ready else "degraded",
        "ready": resources.ready,
        "database": db,                                   # required
        "checkpointer": {"ready": resources.graph is not None, "kind": resources.checkpointer_kind},
        "providers": {                                    # optional: the app still serves data without them
            "groq": {"configured": llm_available(), "model": s.groq_model},
            "gnani_stt": {"configured": stt_available()},
            "gnani_tts": {"configured": tts_available(), "model": s.gnani_tts_model},
        },
        "notes": resources.startup_notes,
    }
