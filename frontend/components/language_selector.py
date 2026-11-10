import streamlit as st

LANGS = ["english", "hindi", "marathi", "hinglish", "tamil", "telugu", "kannada", "malayalam", "bengali", "gujarati", "punjabi"]


def language_badge(conv: dict) -> None:
    lang = conv.get("selected_language")
    st.markdown(f"**Language:** {lang.capitalize()}" if lang else "**Language:** _not chosen yet — the agent asks first_")
