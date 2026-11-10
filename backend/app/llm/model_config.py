"""Per-role LLM settings. The model *name* always comes from environment settings."""
from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings


@dataclass(frozen=True)
class RoleConfig:
    temperature: float
    max_tokens: int
    use_judge_model: bool = False


ROLES: dict[str, RoleConfig] = {
    "supervisor": RoleConfig(0.0, 400),
    "language": RoleConfig(0.0, 120),
    "response": RoleConfig(0.3, 450),
    "translator": RoleConfig(0.0, 300),
    "judge": RoleConfig(0.0, 900, use_judge_model=True),
}


def model_for(role: str) -> str:
    s = get_settings()
    return s.judge_model if ROLES[role].use_judge_model else s.groq_model
