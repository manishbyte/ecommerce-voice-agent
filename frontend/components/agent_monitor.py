"""Live monitor of REAL backend events (conversation_events table) - not simulated animations."""
import streamlit as st

from api import client

ICON = {"tool_called": "🛠️", "tool_completed": "✅", "intent_classified": "🧭", "specialist_started": "▶️",
        "specialist_completed": "⏹️", "action_confirmation_requested": "❓", "action_executed": "⚡",
        "input_guardrail": "🛡️", "output_guardrail": "🛡️", "language_selected": "🗣️", "language_changed": "🗣️",
        "customer_verified": "🔐", "response_generated": "💬", "tts_started": "🔊", "conversation_ended": "🏁",
        "node_error": "❌"}


def agent_monitor(conversation_id: str) -> None:
    ss = st.session_state
    try:
        new = client.events(conversation_id, ss.event_cursor)
    except client.ApiError as e:
        st.error(str(e))
        return
    if new:
        ss.events.extend(new)
        ss.event_cursor = new[-1]["id"]
    events = ss.events
    current = next((e["agent"] for e in reversed(events) if e.get("agent")), None)
    st.markdown(f"**Current agent:** `{current or '—'}`")
    try:
        pa = client.pending_action(conversation_id)["pending_action"]
    except client.ApiError:
        pa = None
    if pa:
        with st.container(border=True):
            st.markdown("**⏳ Pending action**")
            st.write(pa["summary"])
            a, b = st.columns(2)
            if a.button("Confirm", key="pa_ok", type="primary"):
                _decide(conversation_id, "confirm", pa["action_id"])
            if b.button("Reject", key="pa_no"):
                _decide(conversation_id, "reject", pa["action_id"])
    box = st.container(height=420)
    for e in reversed(events[-80:]):
        mark = "🔴" if e["status"] in ("error", "blocked") else ICON.get(e["type"], "•")
        box.markdown(f"{mark} **{e['type']}** · `{e.get('agent') or ''}`  \n<small>{e['summary']} — {e['timestamp'][11:19]}</small>",
                     unsafe_allow_html=True)


def _decide(cid, decision, action_id):
    try:
        client.confirm_action(cid, decision, action_id)
        st.toast("Done" if decision == "confirm" else "Rejected")
    except client.ApiError as e:
        st.error(str(e))
