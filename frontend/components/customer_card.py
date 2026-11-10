import streamlit as st

from utils.session_state import select_customer


def customer_card(c: dict) -> None:
    inactive = c["status"] == "inactive"
    with st.container(border=True):
        st.markdown(f"**{c['full_name']}**  \n`{c['customer_id']}` · {'⛔ inactive' if inactive else c['status']}")
        st.caption(f"📱 {c['mobile_number']}  \n✉️ {c['email']}  \n📍 {c.get('city') or '-'}")
        a, b = st.columns(2)
        a.metric("Orders", c["total_orders"])
        b.metric("Open complaints", c["active_complaints"])
        if st.button("Select customer", key=f"sel_{c['customer_id']}", use_container_width=True):
            select_customer(c["customer_id"])
            st.switch_page("pages/customer_dashboard.py")
