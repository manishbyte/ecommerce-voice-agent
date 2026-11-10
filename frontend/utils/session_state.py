import streamlit as st

DEFAULTS = {"selected_customer": None, "conversation_id": None, "event_cursor": 0, "events": [], "last_eval": None}


def init_state() -> None:
    for k, v in DEFAULTS.items():
        st.session_state.setdefault(k, v)


def select_customer(customer_id: str) -> None:
    st.session_state.selected_customer = customer_id
    st.session_state.conversation_id = None      # a different customer always means a new conversation
    st.session_state.event_cursor, st.session_state.events = 0, []
