"""Centralised application settings (env-driven)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> parents[2] is the project root, independent of the CWD.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5000/ecommerce_voice_agent"
    checkpoint_database_url: str = ""
    checkpoint_schema: str = "langgraph"

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    groq_judge_model: str = ""
    llm_timeout_seconds: float = 30.0

    gnani_api_key: str = ""
    gnani_tts_model: str = "timbre-v2.5"
    stt_sample_rate: int = 16000
    tts_sample_rate: int = 24000

    seed_file: Path = PROJECT_ROOT / "data" / "customers.json"
    reports_dir: Path = BACKEND_ROOT / "app" / "evaluation" / "reports"
    datasets_dir: Path = BACKEND_ROOT / "app" / "evaluation" / "datasets"

    return_window_days: int = 10
    pending_action_ttl_seconds: int = 300
    max_input_chars: int = 1000
    max_response_chars: int = 700

    store_audio: bool = False
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:8501"

    @property
    def checkpoint_dsn(self) -> str:
        url = self.checkpoint_database_url or self.database_url
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)

    @property
    def judge_model(self) -> str:
        return self.groq_judge_model or self.groq_model

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
