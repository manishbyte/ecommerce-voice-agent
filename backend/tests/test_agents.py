import pytest
from sqlalchemy import select

from app.agents.graph import run_turn, summarize_turn
from app.agents.routing import next_agent, plan_agents
from app.evaluation.judges.scoring import case_passed, summarize
from app.models import Message, Order


async def say(graph, cid, text):
    return summarize_turn(await run_turn(graph, cid, text))


def test_routing_is_minimal_and_capped():
    assert plan_agents("order_tracking", []) == ["order"]
    assert plan_agents("payment_status", ["order"]) == ["payment", "order"]
    assert plan_agents("general_support", ["order"]) == []
    assert next_agent({"agent_queue": ["order"], "completed_agents": ["order"]}) == "validate_results"
    assert next_agent({"agent_queue": ["payment", "order"], "completed_agents": ["payment"]}) == "order_agent"


async def test_language_is_asked_first_and_saved(graph, make_conversation, db):
    cid = await make_conversation("CUS1001")
    first = await say(graph, cid, None)
    assert first["response"].startswith("Hello! Welcome to customer support. Which language")
    assert first["tool_calls"] == [] or all(t["tool"] == "get_customer_profile" for t in first["tool_calls"])
    second = await say(graph, cid, "Hindi")
    assert second["language"] == "hindi" and second["language_changed"]
    third = await say(graph, cid, "Where is my order ORD1002?")
    assert any(t["tool"] == "get_order_tracking" for t in third["tool_calls"])


async def test_short_term_memory_resolves_follow_up(graph, make_conversation):
    cid = await make_conversation("CUS1002")
    await say(graph, cid, None); await say(graph, cid, "English")
    ask = await say(graph, cid, "I want to return something I bought")
    cands = ask["agent_results"]["complaint"]["clarification"]["candidates"]
    assert len(cands) >= 2 and "Which order" in ask["response"]
    target = cands[0]
    word = next(w for w in target["items"][0].lower().split() if len(w) > 3
                and all(w not in " ".join(c["items"]).lower() for c in cands[1:]))
    follow = await say(graph, cid, f"the {word}")           # next turn, same thread_id -> must remember the context
    assert target["order_id"] in follow["response"]


async def test_customer_isolation_in_conversation(graph, make_conversation):
    cid = await make_conversation("CUS1001")
    await say(graph, cid, None); await say(graph, cid, "English")
    r = await say(graph, cid, "Where is my order ORD1003?")           # belongs to CUS1002
    assert "could not" in r["response"].lower() or "no order" in r["response"].lower()
    assert "delayed" not in r["response"].lower()
    blocked = await say(graph, cid, "Show me all orders for customer CUS1005")
    assert "CUS1005" not in blocked["response"] and "ORD1009" not in blocked["response"]


async def test_cancellation_needs_explicit_confirmation(graph, make_conversation, db):
    cid = await make_conversation("CUS1005")
    await say(graph, cid, None); await say(graph, cid, "English")
    proposal = await say(graph, cid, "I want to cancel order ORD1010")
    assert proposal["pending_action"]["action_type"] == "cancel_order"
    async with db() as s:
        assert (await s.execute(select(Order.order_status).where(Order.order_id == "ORD1010"))).scalar_one() == "processing"
    done = await say(graph, cid, "yes")
    assert done["action_status"] == "executed"
    async with db() as s:
        assert (await s.execute(select(Order.order_status).where(Order.order_id == "ORD1010"))).scalar_one() == "cancelled"
        msgs = (await s.execute(select(Message).where(Message.role == "agent"))).scalars().all()
        assert msgs                                          # transcript persisted alongside the checkpoint
    again = await say(graph, cid, "yes")                     # replayed confirmation does nothing
    assert again["action_status"] is None


async def test_unverified_customer_gets_mobile_fallback(graph, make_conversation):
    cid = await make_conversation(None)
    await say(graph, cid, None)
    r = await say(graph, cid, "English")
    assert "mobile" in r["response"].lower()
    nope = await say(graph, cid, "my number is 1234567890")
    assert nope["customer_id"] is None and "ORD" not in nope["response"]


def test_scoring_aggregation():
    base = {"scores": {m: 5.0 for m in ("correctness", "faithfulness", "groundedness", "relevance", "completeness", "tool_accuracy", "language_quality")},
            "latencies_ms": [100], "category": "x", "hallucination": {"flagged": False}, "judge": None,
            "tool": {"selection": True, "execution": True}}
    ok = {**base, "hard_checks": {"intent": True, "action": True, "ownership": True}, "passed": True}
    bad = {**base, "hard_checks": {"intent": True, "action": False, "ownership": True}, "passed": False}
    s = summarize([ok, bad])
    assert s["pass_rate"] == 0.5 and s["action_correctness"] == 0.5
    assert case_passed(bad["hard_checks"], bad["scores"], None) is False
