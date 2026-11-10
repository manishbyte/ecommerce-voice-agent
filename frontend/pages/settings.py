import streamlit as st

from api import client
from utils.session_state import init_state

init_state()
st.title("⚙️ Settings & Health")
st.write(f"Backend URL (server-side): `{client.BACKEND_URL}`  ·  Public URL (browser): `{client.PUBLIC_URL}`")
try:
    h = client.health()
    st.json(h)
except client.ApiError as e:
    st.error(str(e))
st.markdown("""
**Microphone requirements** — the voice client needs HTTPS (or `localhost`). Phones and other computers on your
network must reach the backend through an `https://` address; see the README.
""")
st.link_button("Open standalone voice client", client.voice_client_url())
