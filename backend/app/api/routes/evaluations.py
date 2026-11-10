from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, HTTPException

from app.config import get_settings
from app.dependencies import resources
from app.schemas.evaluation import EvaluationRunRequest, EvaluationStatus

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
_RUNNING: dict[str, asyncio.Task] = {}


def _path(eid: str):
    return get_settings().reports_dir / f"{eid}.json"


def _read(eid: str) -> dict | None:
    p = _path(eid)
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


@router.post("/run", response_model=EvaluationStatus, status_code=202)
async def run_evaluation(body: EvaluationRunRequest) -> EvaluationStatus:
    if resources.graph is None:
        raise HTTPException(503, "Agent graph is not ready")
    from app.evaluation.runners.dataset_runner import run_evaluation as _run

    eid = uuid.uuid4().hex[:12]
    get_settings().reports_dir.mkdir(parents=True, exist_ok=True)
    _path(eid).write_text(json.dumps({"evaluation_id": eid, "status": "running", "progress": 0.0}), encoding="utf-8")
    _RUNNING[eid] = asyncio.create_task(_run(eid, resources.graph, datasets=body.datasets, max_cases=body.max_cases,
                                             use_judge=body.use_judge))
    return EvaluationStatus(evaluation_id=eid, status="running")


@router.get("", response_model=list[dict])
async def list_evaluations() -> list[dict]:
    out = []
    for p in sorted(get_settings().reports_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        d = json.loads(p.read_text(encoding="utf-8"))
        out.append({"evaluation_id": d.get("evaluation_id"), "status": d.get("status"), "created_at": d.get("created_at"),
                    "summary": d.get("summary")})
    return out


@router.get("/{evaluation_id}", response_model=EvaluationStatus)
async def get_evaluation(evaluation_id: str) -> EvaluationStatus:
    d = _read(evaluation_id)
    if d is None:
        raise HTTPException(404, "Evaluation not found")
    return EvaluationStatus(evaluation_id=evaluation_id, status=d.get("status", "unknown"), progress=d.get("progress", 0.0),
                            report=d if d.get("status") == "completed" else None, error=d.get("error"))

