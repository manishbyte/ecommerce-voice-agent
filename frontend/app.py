"""Recruiter dashboard entrypoint:  streamlit run frontend/app.py"""
import streamlit as st

from utils.session_state import init_state
from utils.theme import apply_theme

st.set_page_config(page_title="E-commerce Voice Support Agent", page_icon="🎙️", layout="wide")
init_state()
apply_theme()
nav = st.navigation([
    st.Page("pages/voice_support.py", title="Voice Assistant", icon="🎙️", default=True),
    st.Page("pages/customer_directory.py", title="Customers", icon="👥"),
    st.Page("pages/customer_dashboard.py", title="Customer Dashboard", icon="🧾"),
    st.Page("pages/conversation_history.py", title="Conversation History", icon="🗂️"),
    st.Page("pages/change_log.py", title="Change Log", icon="🕘"),
    st.Page("pages/evaluation_dashboard.py", title="Evaluation Dashboard", icon="📊"),
    st.Page("pages/settings.py", title="Settings & Health", icon="⚙️"),
])
if st.session_state.selected_customer:
    st.sidebar.success(f"Selected: {st.session_state.selected_customer}")
nav.run()
