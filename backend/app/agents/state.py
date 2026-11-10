"""LangGraph state definition and a per-node tool runner."""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from app.guardrails.tool_validation import run_tool


class AgentState(TypedDict, total=False):
    # identity / session (conversation_id is also the LangGraph thread_id)
    conversation_id: str
    customer_id: str | None
    customer_verified: bool
    customer_profile: dict
    identity_attempts: int
    identity_just_verified: bool
    # language
    selected_language: str | None
    language_initialized: bool
    language_changed: bool
    # turn input / routing
    current_user_message: str
    current_intent: str | None
    entities: dict
    agent_queue: list[str]
    completed_agents: list[str]
    active_agent: str | None
    # memory (persisted by the checkpointer across turns)
    conversation_history: Annotated[list[AnyMessage], add_messages]
    focus_order_id: str | None
    candidate_order_ids: list[str]
    pending_clarification: dict | None
    # evidence
    relevant_customer_context: dict
    retrieved_records: dict
    agent_results: dict
    tool_execution_history: Annotated[list[dict], operator.add]
    turn_tool_start: int
    notices: list[dict]
    # actions
    pending_action: dict | None
    action_confirmation_status: str | None
    # output
    response: str | None
    response_from_fallback: bool
    output_retries: int
    output_feedback: str | None
    guardrail: dict
    error_state: str | None
    turn_id: int
    end_call: bool


class TurnTools:
    """Runs tools through the validation gateway and remembers the execution records."""

    def __init__(self, state: AgentState, agent: str):
        self.state: dict[str, Any] = {**state, "active_agent": agent}
        self.records: list[dict] = []

    async def __call__(self, name: str, **args) -> dict:
        result, rec = await run_tool(self.state, name, **args)
        self.records.append(rec)
        return result


def merge_result(state: AgentState, name: str, result: dict, tools: "TurnTools", **extra) -> dict:
    """Standard specialist return: store result, mark agent complete, append tool records."""
    return {
        "agent_results": {**state.get("agent_results", {}), name: result},
        "completed_agents": [*state.get("completed_agents", []), name],
        "tool_execution_history": tools.records,
        **extra,
    }
