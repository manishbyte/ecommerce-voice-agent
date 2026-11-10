"""Run datasets, persist progress + the final report under evaluation/reports/."""
from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime

from app.config import get_settings
from app.evaluation.evaluation_config import DATASET_FILES
from app.evaluation.judges.scoring import summarize
from app.evaluation.runners.conversation_runner import run_case
from app.llm.groq_client import llm_available

log = logging.getLogger(__name__)


def load_cases(datasets: list[str] | None, max_cases: int | None) -> list[tuple[str, dict]]:
    base = get_settings().datasets_dir
    out: list[tuple[str, dict]] = []
    for name in datasets or list(DATASET_FILES):
        if name not in DATASET_FILES:
            raise ValueError(f"unknown dataset '{name}'")
        for line in (base / DATASET_FILES[name]).read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append((name, json.loads(line)))
    return out[:max_cases] if max_cases else out


def _write(eid: str, payload: dict) -> None:
    d = get_settings().reports_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{eid}.json").write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")


async def run_evaluation(eid: str, graph, *, datasets: list[str] | None = None, max_cases: int | None = None,
                         use_judge: bool = True) -> dict:
    created = datetime.utcnow().isoformat()
    judge_on = use_judge and llm_available()
    try:
        cases = load_cases(datasets, max_cases)
        results: list[dict] = []
        for i, (ds, case) in enumerate(cases, 1):
            try:
                results.append(await run_case(graph, case, ds, judge_on))
            except Exception as exc:  # noqa: BLE001  -> a crashing case is a failed case, not a crashed run
                log.exception("case %s crashed", case.get("test_id"))
                results.append({"test_id": case.get("test_id"), "dataset": ds, "category": case.get("category", ""),
                                "customer_id": case.get("customer_id"), "language": case.get("language"),
                                "queries": [case.get("query")], "responses": [], "response": "", "intent": None,
                                "expected_intent": case.get("expected_intent"), "tools": [],
                                "tool": {"selection": False, "execution": False, "detail": "crashed"},
                                "scores": {m: 1.0 for m in ("correctness", "faithfulness", "groundedness", "relevance",
                                                            "completeness", "tool_accuracy", "language_quality")},
                                "deterministic": {}, "judge": None, "hallucination": {"flagged": False},
                                "hard_checks": {"no_crash": False}, "passed": False, "latencies_ms": [],
                                "failure_reason": f"crash: {type(exc).__name__}: {exc}", "traceback": traceback.format_exc()[-600:]})
            _write(eid, {"evaluation_id": eid, "status": "running", "progress": round(i / len(cases), 3), "created_at": created})
        report = {"evaluation_id": eid, "status": "completed", "progress": 1.0, "created_at": created,
                  "finished_at": datetime.utcnow().isoformat(),
                  "config": {"datasets": datasets or list(DATASET_FILES), "max_cases": max_cases, "judge": judge_on,
                             "response_model": get_settings().groq_model, "judge_model": get_settings().judge_model if judge_on else None},
                  "summary": summarize(results),
                  "by_dataset": {ds: summarize([r for r in results if r["dataset"] == ds]) for ds in {r["dataset"] for r in results}},
                  "failed_cases": [r["test_id"] for r in results if not r["passed"]], "cases": results}
        _write(eid, report)
        return report
    except Exception as exc:  # noqa: BLE001
        log.exception("evaluation %s failed", eid)
        _write(eid, {"evaluation_id": eid, "status": "failed", "error": f"{type(exc).__name__}: {exc}", "created_at": created})
        raise
