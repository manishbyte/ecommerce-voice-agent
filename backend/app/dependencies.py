"""Process-wide resources created once at startup (never per request)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.database.connection import get_session  # re-exported FastAPI dependency

__all__ = ["resources", "get_session", "Resources"]


@dataclass
class Resources:
    graph: Any = None
    checkpointer: Any = None
    checkpoint_pool: Any = None
    ready: bool = False
    shutting_down: bool = False
    checkpointer_kind: str = "none"
    startup_notes: list[str] = field(default_factory=list)


resources = Resources()
