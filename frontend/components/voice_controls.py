"""Embeds the backend-served voice client (works with laptop, phone and tablet microphones)."""
import streamlit as st
import streamlit.components.v1 as components

from api.client import PUBLIC_URL, voice_client_url


def voice_controls(conversation_id: str) -> None:
    url = voice_client_url(conversation_id)
    components.html(f'<iframe src="{url}" allow="microphone; autoplay" '
                    f'style="width:100%;height:660px;border:1px solid #8884;border-radius:12px"></iframe>', height=670)
    st.link_button("🔗 Open voice client in its own tab / on your phone", url, use_container_width=True)
    if not PUBLIC_URL.startswith("https://") and "localhost" not in PUBLIC_URL and "127.0.0.1" not in PUBLIC_URL:
        st.warning("The microphone only works on HTTPS or localhost. Set BACKEND_PUBLIC_URL to an https:// address "
                   "(see README → Using the microphone on a phone or another device).")
