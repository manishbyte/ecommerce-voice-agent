import streamlit as st


def customer_profile(p: dict, compact: bool = False) -> None:
    a = p.get("address") or {}
    st.markdown(f"### {p['full_name']}")
    st.caption(f"`{p['customer_id']}` · {p['status']}")
    st.write(f"📱 {p['mobile_number']}")
    st.write(f"✉️ {p['email']}")
    if not compact:
        st.write(f"🎂 {p.get('date_of_birth') or '-'}  ·  🗣️ preferred: {p.get('preferred_language') or '-'}")
    st.write("📍 " + ", ".join(x for x in [a.get("line1"), a.get("line2"), a.get("city"), a.get("state"), a.get("postal_code")] if x))
