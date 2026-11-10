"""LLM-as-a-Judge (separate model via GROQ_JUDGE_MODEL) with structured 1-5 scoring."""
from __future__ import annotations

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

from app.evaluation.judges.judge_prompts import JUDGE_SYSTEM, JUDGE_USER, REFERENCE_CASES
from app.llm.structured_output import structured_invoke

log = logging.getLogger(__name__)
Score = Field(ge=1, le=5)


class JudgeResult(BaseModel):
    correctness: int = Score
    faithfulness: int = Score
    groundedness: int = Score
    relevance: int = Score
    completeness: int = Score
    language_quality: int = Score
    hallucination: bool
    overall_pass: bool
    explanation: str
    evidence: list[str] = Field(default_factory=list)
    failure_category: Literal["none", "wrong_facts", "hallucination", "missing_info", "wrong_tool", "privacy_violation",
                              "unsafe_action", "wrong_language", "poor_clarification", "other"] = "none"


async def judge(case: dict, queries: list[str], response: str, context: object, tools: list[str]) -> JudgeResult | None:
    human = JUDGE_USER.format(language=case.get("language"), queries=" | ".join(queries),
                              context=json.dumps(context, ensure_ascii=False, default=str)[:6000], tools=tools,
                              behavior=case.get("expected_behavior"), forbidden=case.get("forbidden_claims"), response=response)
    try:
        return await structured_invoke(JudgeResult, [("system", JUDGE_SYSTEM), ("human", human)], role="judge")
    except Exception as exc:  # noqa: BLE001
        log.warning("judge unavailable: %s", exc)
        return None


async def calibrate_judge() -> dict:
    """Compare the judge with the human labels in judge_prompts.REFERENCE_CASES."""
    agree_pass = agree_hal = n = 0
    rows = []
    for ref in REFERENCE_CASES:
        r = await judge(ref["case"], [ref["case"]["query"]], ref["response"], ref["context"], ref["tools"])
        if r is None:
            continue
        n += 1
        agree_pass += int(r.overall_pass == ref["human_pass"])
        agree_hal += int(r.hallucination == ref["human_hallucination"])
        rows.append({"id": ref["id"], "judge_pass": r.overall_pass, "human_pass": ref["human_pass"],
                     "judge_hallucination": r.hallucination, "human_hallucination": ref["human_hallucination"]})
    return {"n": n, "pass_agreement": agree_pass / n if n else None, "hallucination_agreement": agree_hal / n if n else None, "rows": rows}
