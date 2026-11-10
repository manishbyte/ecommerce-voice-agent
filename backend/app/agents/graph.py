"""Central LangGraph workflow (async) with PostgreSQL-backed short-term memory.

START -> begin_turn -> customer_context -> [language_agent | identity] -> input_guardrails
      -> [confirm/reject | supervisor -> specialists...] -> validate_results -> response_agent
      -> output_guardrails -> save_state -> END
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections import defaultdict
from functools import wraps

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from app.database.base import utcnow
from app.agents.complaint_agent import complaint_agent_node
from app.agents.customer_context import customer_context_node, identity_node
from app.agents.language_agent import language_node, needs_language_node
from app.agents.order_agent import order_agent_node
from app.agents.payment_agent import payment_agent_node
from app.agents.product_agent import product_agent_node
from app.agents.profile_agent import profile_agent_node
from app.agents.refund_agent import refund_agent_node
from app.agents.response_agent import render_fallback, build_facts, response_agent_node
from app.agents.routing import next_agent
from app.agents.state import AgentState
from app.agents.supervisor import supervisor_node
from app.config import get_settings
from app.core.logging import emit_event
from app.database.connection import get_sessionmaker
from app.guardrails.action_confirmation import classify_confirmation, confirm_pending_action, get_pending_action
from app.guardrails.hallucination_check import check_grounding
from app.guardrails.input_validation import validate_user_input
from app.guardrails.output_validation import validate_output
from app.guardrails.prompt_injection import detect_prompt_injection
from app.guardrails.customer_authorization import find_foreign_identifiers
from app.models import Conversation, Customer, Message, Product

log = logging.getLogger(__name__)
SAFE_ERROR = "Sorry, I ran into a problem on my side. Could you please repeat that?"
SPECIALISTS = ("order", "product", "payment", "refund", "complaint", "profile")


def guarded(name: str):
    """Node wrapper: a crashing node degrades to a safe reply instead of killing the call."""
    def deco(fn):
        @wraps(fn)
        async def wrapper(state: AgentState) -> dict:
            try:
                return await fn(state)
            except Exception as exc:  # noqa: BLE001
                log.exception("node %s failed", name)
                await emit_event(state.get("conversation_id"), "node_error", agent=name, status="error",
                                 summary=type(exc).__name__)
                upd: dict = {"error_state": f"{name}:{type(exc).__name__}"}
                if name.replace("_agent", "") in SPECIALISTS:
                    upd["completed_agents"] = [*state.get("completed_agents", []), name.replace("_agent", "")]
                    upd["agent_results"] = {**state.get("agent_results", {}),
                                            name.replace("_agent", ""): {"error": "I couldn't retrieve that information right now."}}
                else:
                    upd["response"] = SAFE_ERROR
                    upd["response_from_fallback"] = True
                return upd
        return wrapper
    return deco


# -------------------------------------------------- nodes --------------------------------------------------
@guarded("begin_turn")
async def begin_turn(state: AgentState) -> dict:
    """Load Conversation Context: the DB (not the client) decides customer + language."""
    conv_id = state["conversation_id"]
    async with get_sessionmaker()() as s:
        conv = await s.get(Conversation, uuid.UUID(conv_id))
        cust = await s.get(Customer, conv.customer_pk) if conv and conv.customer_pk else None
    msg = (state.get("current_user_message") or "").strip()
    upd: dict = {
        "turn_id": state.get("turn_id", 0) + 1, "agent_results": {}, "completed_agents": [], "agent_queue": [],
        "entities": {}, "response": None, "response_from_fallback": False, "notices": [], "guardrail": {},
        "error_state": None, "current_intent": None, "output_retries": 0, "output_feedback": None,
        "turn_tool_start": len(state.get("tool_execution_history", [])), "language_changed": False,
        "identity_just_verified": False, "action_confirmation_status": None, "active_agent": None,
        "customer_id": cust.customer_id if cust else None, "customer_verified": cust is not None,
        "selected_language": conv.selected_language if conv else None,
        "language_initialized": bool(conv and conv.selected_language),
        "pending_action": await get_pending_action(conv_id),
        "end_call": False,
    }
    if msg:
        upd["conversation_history"] = [HumanMessage(content=msg)]
    await emit_event(conv_id, "turn_started", agent="graph", summary=f"Turn {upd['turn_id']} started")
    return upd


customer_context = guarded("customer_context")(customer_context_node)
language_agent = guarded("language_agent")(language_node)
identity = guarded("identity")(identity_node)
supervisor = guarded("supervisor")(supervisor_node)


@guarded("input_guardrails")
async def input_guardrails(state: AgentState) -> dict:
    conv = state["conversation_id"]
    s = get_settings()
    res, cleaned = validate_user_input(state.get("current_user_message"), s.max_input_chars)
    gr = res
    if res.passed:
        inj = detect_prompt_injection(cleaned)
        if not inj.passed:
            gr = inj
        else:
            foreign = find_foreign_identifiers(cleaned, state.get("customer_id"))
            if foreign["foreign_customers"]:
                from app.guardrails import GuardrailResult
                gr = GuardrailResult(False, "cross_customer_request", "other customer id referenced", foreign)
    await emit_event(conv, "input_guardrail", agent="guardrails", status="ok" if gr.passed else "blocked",
                     summary="Input passed" if gr.passed else f"Input blocked: {gr.code}", data={"code": gr.code})
    upd: dict = {"current_user_message": cleaned, "guardrail": {"input": gr.as_dict()}}
    if not gr.passed:
        upd["notices"] = [{"type": "blocked", "reason": gr.code}]
        upd["current_intent"] = "general_support"
    return upd


def route_after_input(state: AgentState) -> str:
    if state.get("error_state"):
        return "save_state"
    if state.get("guardrail", {}).get("input", {}).get("passed") is False:
        return "response_agent"
    if state.get("pending_action"):
        decision = classify_confirmation(state.get("current_user_message", ""))
        if decision == "confirm":
            return "confirm_action"
        if decision == "reject":
            return "reject_action"
    return "supervisor"


async def _resolve_pending(state: AgentState, decision: str) -> dict:
    pa = state.get("pending_action") or {}
    out = await confirm_pending_action(state["conversation_id"], decision, pa.get("action_id"))
    return {"agent_results": {"confirmation": out}, "completed_agents": ["confirmation"], "pending_action": None,
            "action_confirmation_status": out.get("status"), "current_intent": "action_confirmation",
            "active_agent": "confirmation"}


@guarded("confirm_action")
async def confirm_action(state: AgentState) -> dict:
    return await _resolve_pending(state, "confirm")


@guarded("reject_action")
async def reject_action(state: AgentState) -> dict:
    return await _resolve_pending(state, "reject")


def _scrub(obj, customer_id: str):
    """Defence in depth: drop any record stamped with a different customer id."""
    if isinstance(obj, dict):
        if obj.get("customer_id") not in (None, customer_id):
            return None
        return {k: v for k, v in ((k, _scrub(v, customer_id)) for k, v in obj.items()) if v is not None or k in obj and obj[k] is None}
    if isinstance(obj, list):
        return [x for x in (_scrub(v, customer_id) for v in obj) if x is not None]
    return obj


@guarded("validate_results")
async def validate_results(state: AgentState) -> dict:
    cid = state.get("customer_id")
    results = state.get("agent_results", {})
    clean = _scrub(results, cid) if cid else results
    violation = clean != results
    tool_errors = [r for r in state.get("tool_execution_history", [])[state.get("turn_tool_start", 0):] if not r["ok"]]
    await emit_event(state["conversation_id"], "results_validated", agent="validator",
                     status="error" if violation else "ok",
                     summary="Cross-customer data removed" if violation else f"{len(results)} result set(s) verified",
                     data={"tool_errors": len(tool_errors)})
    upd = {"agent_results": clean, "retrieved_records": {"agents": list(clean)}}
    if violation:
        upd["error_state"] = "cross_customer_data_removed"
    return upd


response_agent = guarded("response_agent")(response_agent_node)

_names_cache: dict[str, list[str]] = {}


async def _known_names() -> tuple[list[str], dict[str, str]]:
    if "products" not in _names_cache:
        async with get_sessionmaker()() as s:
            _names_cache["products"] = [n for (n,) in (await s.execute(select(Product.name))).all()]
            _names_cache["customers"] = [f"{cid}|{n}" for cid, n in (await s.execute(select(Customer.customer_id, Customer.full_name))).all()]
    return _names_cache["products"], {x.split("|")[0]: x.split("|")[1] for x in _names_cache["customers"]}


@guarded("output_guardrails")
async def output_guardrails(state: AgentState) -> dict:
    conv, cid = state["conversation_id"], state.get("customer_id")
    text = state.get("response") or ""
    if state.get("response_from_fallback") or state.get("current_intent") == "language_selection":
        return {"guardrail": {**state.get("guardrail", {}), "output": {"passed": True, "skipped": "static/fallback"}}}
    products, customers = await _known_names()
    foreign = [n for k, n in customers.items() if k != cid]
    evidence = {"results": state.get("agent_results", {}), "profile": state.get("customer_profile", {}),
                "pending": state.get("pending_action")}
    allowed_numbers = re.findall(r"\d{10}", json.dumps(evidence, default=str))   # e.g. the new mobile being confirmed
    structural = validate_output(text, language_key=state.get("selected_language"), max_chars=get_settings().max_response_chars,
                                 allowed_numbers=allowed_numbers)
    grounding = check_grounding(text, evidence, catalogue_names=products, foreign_names=foreign,
                                extra_allowed=[state.get("current_user_message", "")]).to_result()
    bad = structural if not structural.passed else grounding
    await emit_event(conv, "output_guardrail", agent="guardrails", status="ok" if bad.passed else "blocked",
                     summary="Response grounded" if bad.passed else f"Response rejected: {bad.code}", data=bad.as_dict())
    gr = {**state.get("guardrail", {}), "output": bad.as_dict()}
    if bad.passed:
        return {"guardrail": gr}
    if state.get("output_retries", 0) < 1:
        return {"guardrail": gr, "output_retries": 1,
                "output_feedback": f"{bad.code}: {bad.details or bad.message}"}
    safe = render_fallback(build_facts(state))
    return {"guardrail": gr, "response": safe, "response_from_fallback": True, "output_feedback": None}


def route_after_output(state: AgentState) -> str:
    return "response_agent" if state.get("output_feedback") else "save_state"


@guarded("save_state")
async def save_state(state: AgentState) -> dict:
    conv_id = state["conversation_id"]
    response = state.get("response") or SAFE_ERROR
    tools_used = [r["tool"] for r in state.get("tool_execution_history", [])[state.get("turn_tool_start", 0):]]
    async with get_sessionmaker()() as s:
        async with s.begin():
            cu = uuid.UUID(conv_id)
            msg = (state.get("current_user_message") or "").strip()
            if msg:
                s.add(Message(conversation_pk=cu, role="customer", content=msg,
                              meta={"turn": state.get("turn_id")}))
            s.add(Message(conversation_pk=cu, role="agent", content=response,
                          agent_name=state.get("active_agent") or "response",
                          meta={"intent": state.get("current_intent"), "agents": state.get("completed_agents", []),
                                "tools": tools_used, "language": state.get("selected_language"),
                                "pending_action": (state.get("pending_action") or {}).get("action_id"),
                                "guardrail": state.get("guardrail", {}), "turn": state.get("turn_id")}))
            if state.get("end_call"):
                conv = await s.get(Conversation, cu)
                conv.status, conv.ended_at = "ended", utcnow()
    await emit_event(conv_id, "turn_saved", agent="graph", summary="Conversation state saved")
    return {"response": response, "conversation_history": [AIMessage(content=response)]}


# ------------------------------------------------- wiring -------------------------------------------------
def _route_language(state: AgentState) -> str:
    if state.get("error_state"):
        return "save_state"
    return "language_agent" if needs_language_node(state) else "identity"


def _after_language(state: AgentState) -> str:
    return "save_state" if (state.get("response") or state.get("error_state")) else "response_agent"


def _after_identity(state: AgentState) -> str:
    if state.get("error_state"):
        return "save_state"
    if state.get("customer_verified") and not state.get("identity_just_verified"):
        return "input_guardrails"
    return "response_agent"


def build_graph(checkpointer):
    g = StateGraph(AgentState)
    g.add_node("begin_turn", begin_turn)
    g.add_node("customer_context", customer_context)
    g.add_node("language_agent", language_agent)
    g.add_node("identity", identity)
    g.add_node("input_guardrails", input_guardrails)
    g.add_node("confirm_action", confirm_action)
    g.add_node("reject_action", reject_action)
    g.add_node("supervisor", supervisor)
    for name, fn in (("order", order_agent_node), ("product", product_agent_node), ("payment", payment_agent_node),
                     ("refund", refund_agent_node), ("complaint", complaint_agent_node),
                     ("profile", profile_agent_node)):
        g.add_node(f"{name}_agent", guarded(f"{name}_agent")(fn))
    g.add_node("validate_results", validate_results)
    g.add_node("response_agent", response_agent)
    g.add_node("output_guardrails", output_guardrails)
    g.add_node("save_state", save_state)

    g.add_edge(START, "begin_turn")
    g.add_edge("begin_turn", "customer_context")
    g.add_conditional_edges("customer_context", _route_language,
                            {"language_agent": "language_agent", "identity": "identity", "save_state": "save_state"})
    g.add_conditional_edges("language_agent", _after_language, {"save_state": "save_state", "response_agent": "response_agent"})
    g.add_conditional_edges("identity", _after_identity,
                            {"input_guardrails": "input_guardrails", "response_agent": "response_agent", "save_state": "save_state"})
    g.add_conditional_edges("input_guardrails", route_after_input,
                            {"response_agent": "response_agent", "confirm_action": "confirm_action",
                             "reject_action": "reject_action", "supervisor": "supervisor", "save_state": "save_state"})
    g.add_edge("confirm_action", "validate_results")
    g.add_edge("reject_action", "validate_results")
    spec_map = {f"{n}_agent": f"{n}_agent" for n in SPECIALISTS} | {"validate_results": "validate_results"}
    g.add_conditional_edges("supervisor", next_agent, spec_map)
    for n in SPECIALISTS:
        g.add_conditional_edges(f"{n}_agent", next_agent, spec_map)
    g.add_edge("validate_results", "response_agent")
    g.add_edge("response_agent", "output_guardrails")
    g.add_conditional_edges("output_guardrails", route_after_output, {"response_agent": "response_agent", "save_state": "save_state"})
    g.add_edge("save_state", END)
    return g.compile(checkpointer=checkpointer)


# ------------------------------------------------ execution ------------------------------------------------
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def run_turn(graph, conversation_id: str, text: str | None) -> dict:
    """Run one customer turn on the conversation's LangGraph thread (thread_id == conversation_id).

    `text=None` (or empty) on a fresh conversation produces the language-selection greeting.
    """
    config = {"configurable": {"thread_id": conversation_id}}
    inputs = {"conversation_id": conversation_id, "current_user_message": text or ""}
    final: dict = {}
    async with _locks[conversation_id]:
        async for chunk in graph.astream(inputs, config, stream_mode="values"):
            final = chunk
    return final


def summarize_turn(final: dict) -> dict:
    start = final.get("turn_tool_start", 0)
    return {"response": final.get("response"), "language": final.get("selected_language"),
            "language_changed": bool(final.get("language_changed")), "intent": final.get("current_intent"),
            "agents": final.get("completed_agents", []), "pending_action": final.get("pending_action"),
            "tool_calls": final.get("tool_execution_history", [])[start:], "guardrail": final.get("guardrail", {}),
            "customer_id": final.get("customer_id"), "action_status": final.get("action_confirmation_status"),
            "agent_results": final.get("agent_results", {}), "error": final.get("error_state"),
            "end_call": bool(final.get("end_call"))}
         
