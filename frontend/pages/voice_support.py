import streamlit as st
import streamlit.components.v1 as components

from api import client
from components.agent_monitor import agent_monitor
from components.customer_profile import customer_profile
from components.transcript import transcript
from utils.session_state import init_state

init_state()
ss = st.session_state
cid = ss.selected_customer

head_l, head_r = st.columns([3, 2])
head_l.markdown("### 🎙️ Voice Assistant")
if cid:
    head_r.caption(f"Customer selected: **{cid}** — the call will start with this customer.")
else:
    head_r.caption("Tap the speaker and pick a customer inside the call window.")

url = client.voice_client_url(customer_id=cid)
components.html(f'<iframe src="{url}" allow="microphone; autoplay" '
                f'style="width:100%;height:790px;border:1px solid #333;border-radius:18px;background:#212121"></iframe>', height=800)
c1, c2 = st.columns([1, 1])
c1.link_button("🔗 Open in its own tab / on your phone", url, use_container_width=True)
if not client.PUBLIC_URL.startswith("https://") and "localhost" not in client.PUBLIC_URL and "127.0.0.1" not in client.PUBLIC_URL:
    c2.warning("The microphone needs HTTPS")


def latest_session() -> dict | None:
    try:
        for c in client.list_conversations():
            if c["resolution_status"] != "evaluation":
                return c
    except client.ApiError:
        return None
    return None


t_act, t_tx, t_cust = st.tabs(["Live agent activity", "Transcript", "Customer"])
with t_act:
    @st.fragment(run_every=2)
    def live_monitor():
        conv = latest_session()
        if not conv:
            st.caption("Start a call to see live agent events (latest session).")
            return
        if ss.conversation_id != conv["conversation_id"]:
            ss.conversation_id, ss.event_cursor, ss.events = conv["conversation_id"], 0, []
        st.caption(f"Latest session `{conv['conversation_id'][:8]}` · {conv['customer_id'] or 'unverified'} · {conv['status']}")
        agent_monitor(conv["conversation_id"])
    live_monitor()
with t_tx:
    @st.fragment(run_every=2)
    def live_transcript():
        conv = latest_session()
        if conv:
            transcript(conv["conversation_id"], height=420)
        else:
            st.caption("No conversation yet.")
    live_transcript()
with t_cust:
    conv = latest_session()
    who = (conv or {}).get("customer_id") or cid
    if who:
        try:
            customer_profile(client.customer_detail(who)["profile"])
        except client.ApiError as e:
            st.error(str(e))
    else:
        st.caption("No customer yet.")
