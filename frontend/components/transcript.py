import streamlit as st

from api import client


def transcript(conversation_id: str, height: int = 360) -> None:
    box = st.container(height=height)
    try:
        msgs = client.messages(conversation_id)
    except client.ApiError as e:
        box.error(str(e))
        return
    if not msgs:
        box.caption("No messages yet.")
    for m in msgs:
        with box.chat_message("user" if m["role"] == "customer" else "assistant"):
            st.write(m["content"])
