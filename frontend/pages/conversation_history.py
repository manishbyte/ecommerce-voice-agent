import streamlit as st

from api import client
from utils.session_state import init_state

init_state()
st.title("🗂️ Conversation History")
only = st.toggle("Only the selected customer", value=bool(st.session_state.selected_customer))
show_eval = st.toggle("Include evaluation runs", value=False)
try:
    convs = client.list_conversations(st.session_state.selected_customer if only else None)
except client.ApiError as e:
    st.error(str(e))
    st.stop()
if not show_eval:
    convs = [c for c in convs if c["resolution_status"] != "evaluation"]
if not convs:
    st.info("No conversations yet.")
for c in convs:
    with st.expander(f"{c['started_at'][:19]} · {c['customer_id'] or 'unverified'} · {c['selected_language'] or 'no language'} · {c['status']}"):
        for m in client.messages(c["conversation_id"]):
            with st.chat_message("user" if m["role"] == "customer" else "assistant"):
                st.write(m["content"])
                meta = m.get("metadata") or {}
                if meta.get("tools"):
                    st.caption("tools: " + ", ".join(meta["tools"]))
