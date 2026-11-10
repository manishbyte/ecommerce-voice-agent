from __future__ import annotations

from pydantic import BaseModel, Field


class EvaluationRunRequest(BaseModel):
    datasets: list[str] | None = None
    max_cases: int | None = Field(default=None, ge=1, le=500)
    use_judge: bool = True


class EvaluationStatus(BaseModel):
    evaluation_id: str
    status: str
    progress: float = 0.0
    report: dict | None = None
    error: str | None = None
