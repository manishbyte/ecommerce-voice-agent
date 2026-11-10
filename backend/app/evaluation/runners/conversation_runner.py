"""Run one evaluation case as a real multi-turn conversation through the production graph."""
from __future__ import annotations

import time

from sqlalchemy import delete, func, select, update

from app.agents.graph import run_turn, summarize_turn
from app.database.connection import get_sessionmaker
from app.evaluation.evaluation_config import PASS_SCORE
from app.evaluation.judges import llm_judge, scoring
from app.evaluation.metrics.completeness import completeness
from app.evaluation.metrics.correctness import correctness, forbidden_hits
from app.evaluation.metrics.faithfulness import faithfulness
from app.evaluation.metrics.groundedness import groundedness
from app.evaluation.metrics.hallucination import hallucination
from app.evaluation.metrics.language_quality import language_quality
from app.evaluation.metrics.relevance import relevance
from app.evaluation.metrics.tool_accuracy import tool_accuracy
from app.models import ChangeLog, Conversation, Customer, Order, PendingAction, Refund, SupportTicket
from app.utils.identifiers import find_ids


async def _snapshot(customer_pk) -> dict:
    async with get_sessionmaker()() as s:
        orders = {o.id: o.order_status for o in (await s.execute(select(Order).where(Order.customer_pk == customer_pk))).scalars()}
        addresses = {o.id: dict(o.shipping_address or {}) for o in (await s.execute(select(Order).where(Order.customer_pk == customer_pk))).scalars()}
        c = await s.get(Customer, customer_pk)
        profile = {"full_name": c.full_name, "email": c.email, "mobile_number": c.mobile_number,
                   "preferred_language": c.preferred_language, "address": dict(c.address or {}), "status": c.status}
        last_log = (await s.execute(select(func.coalesce(func.max(ChangeLog.id), 0)))).scalar_one()
        refunds = set((await s.execute(select(Refund.refund_id))).scalars())
        tickets = set((await s.execute(select(SupportTicket.ticket_id))).scalars())
    return {"orders": orders, "refunds": refunds, "tickets": tickets, "addresses": addresses, "profile": profile,
            "customer_pk": customer_pk, "last_log": last_log}


async def _restore(snap: dict) -> None:
    """Evaluation must never permanently change the demo data."""
    async with get_sessionmaker()() as s:
        async with s.begin():
            for pk, status in snap["orders"].items():
                await s.execute(update(Order).where(Order.id == pk).values(order_status=status))
            for pk, addr in snap["addresses"].items():
                await s.execute(update(Order).where(Order.id == pk).values(shipping_address=addr))
            await s.execute(update(Customer).where(Customer.id == snap["customer_pk"]).values(**snap["profile"]))
            await s.execute(delete(ChangeLog).where(ChangeLog.id > snap["last_log"]))
            await s.execute(delete(Refund).where(Refund.refund_id.not_in(snap["refunds"])))
            await s.execute(delete(SupportTicket).where(SupportTicket.ticket_id.not_in(snap["tickets"])))


async def _check_action(case: dict, conv_pk, summaries: list[dict]) -> tuple[bool, str]:
    exp = case.get("expected_action_outcome")
    if not exp:
        return True, "n/a"
    kind = exp["type"]
    final = summaries[-1]
    async with get_sessionmaker()() as s:
        rows = (await s.execute(select(PendingAction).where(PendingAction.conversation_pk == conv_pk))).scalars().all()
        executed = [r for r in rows if r.status == "executed"]
        if kind == "proposal":
            ok = any(sm.get("pending_action") and sm["pending_action"]["action_type"] == exp["action"] for sm in summaries) \
                or any(r.action_type == exp["action"] for r in rows)
            return ok and not executed, f"proposals={[r.action_type for r in rows]} executed={len(executed)}"
        if kind == "executed":
            ok = any(r.action_type == exp["action"] for r in executed)
            if ok and exp.get("new_status"):
                o = (await s.execute(select(Order).where(Order.order_id == exp["order_id"]))).scalar_one()
                ok = o.order_status == exp["new_status"]
            return ok, f"executed={[r.action_type for r in executed]}"
        if kind == "none":
            return not executed and not final.get("pending_action"), f"executed={len(executed)} pending={bool(final.get('pending_action'))}"
        if kind == "none_executed":
            o = (await s.execute(select(Order).where(Order.order_id == exp["order_id"]))).scalar_one()
            return (not executed) and o.order_status == exp["unchanged_status"], f"status={o.order_status}"
        if kind == "language_change":
            return final.get("language") == exp["language"], f"language={final.get('language')}"
    return False, f"unknown action expectation {kind}"


async def run_case(graph, case: dict, dataset: str, use_judge: bool) -> dict:
    queries = [case["query"], *case.get("follow_ups", [])]
    async with get_sessionmaker()() as s:
        cust = (await s.execute(select(Customer).where(Customer.customer_id == case["customer_id"]))).scalar_one()
    snap = await _snapshot(cust.id)
    conv = Conversation(customer_pk=cust.id, resolution_status="evaluation")
    async with get_sessionmaker()() as s:
        s.add(conv)
        await s.commit()
    cid = str(conv.id)
    try:
        await run_turn(graph, cid, None)                                        # greeting (not scored)
        start_lang = "english" if (case.get("expected_action_outcome") or {}).get("type") == "language_change" else case["language"]
        await run_turn(graph, cid, start_lang.capitalize())                     # language selection (not scored)
        summaries, latencies = [], []
        for q in queries:
            t0 = time.perf_counter()
            final = await run_turn(graph, cid, q)
            latencies.append(round((time.perf_counter() - t0) * 1000))
            summaries.append(summarize_turn(final))
        action_ok, action_detail = await _check_action(case, conv.id, summaries)
    finally:
        await _restore(snap)

    responses = [sm["response"] or "" for sm in summaries]
    full_text, last = " ".join(responses), responses[-1]
    tool_calls = [t for sm in summaries for t in sm["tool_calls"]]
    evidence = {f"turn{i + 1}": sm["agent_results"] for i, sm in enumerate(summaries)}
    user_text = " ".join(queries)
    lang = summaries[-1].get("language") or case["language"]
    if (case.get("expected_action_outcome") or {}).get("type") == "language_change":
        lang = case["expected_action_outcome"]["language"]

    det = {"correctness": correctness(case, full_text), "faithfulness": faithfulness(full_text, evidence, user_text),
           "groundedness": groundedness(full_text, evidence, user_text),
           "relevance": relevance(case, summaries[0]["intent"], full_text), "completeness": completeness(case, full_text),
           "tool_accuracy": tool_accuracy(case, tool_calls), "language_quality": language_quality(lang, last)}
    hal = hallucination(case, full_text, evidence, user_text)
    foreign_customers = [c for c in find_ids(full_text, "CUS") if c != case["customer_id"]]
    hard = {"intent": (not case.get("expected_intent")) or summaries[0]["intent"] == case["expected_intent"],
            "ownership": all(sm["customer_id"] == case["customer_id"] for sm in summaries) and not foreign_customers,
            "forbidden_claims": not forbidden_hits(full_text, case.get("forbidden_claims") or []),
            "action": action_ok, "no_hallucination": not hal["flagged"]}

    judge_out = None
    if use_judge:
        jr = await llm_judge.judge(case, queries, full_text, evidence, [t["tool"] for t in tool_calls])
        judge_out = jr.model_dump() if jr else None
    scores = scoring.case_scores(det, judge_out)
    passed = scoring.case_passed(hard, scores, judge_out)
    reasons = [k for k, v in hard.items() if not v] + [m for m in ("correctness", "faithfulness", "groundedness", "completeness")
                                                       if scores[m] < PASS_SCORE]
    return {"test_id": case["test_id"], "dataset": dataset, "category": case.get("category", ""), "customer_id": case["customer_id"],
            "language": case["language"], "queries": queries, "responses": responses, "response": last,
            "intent": summaries[0]["intent"], "expected_intent": case.get("expected_intent"),
            "tools": [t["tool"] for t in tool_calls], "tool": {"selection": det["tool_accuracy"]["selection"],
                                                              "execution": det["tool_accuracy"]["execution"],
                                                              "detail": det["tool_accuracy"]["detail"]},
            "scores": scores, "deterministic": det, "judge": judge_out, "hallucination": hal, "hard_checks": hard,
            "action_detail": action_detail, "passed": passed, "latencies_ms": latencies,
            "failure_reason": ", ".join(reasons), "conversation_id": cid,
            "expected_behavior": case.get("expected_behavior")}

