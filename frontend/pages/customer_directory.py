import streamlit as st

from api import client
from components.customer_card import customer_card
from components.customer_forms import add_customer_form, demo_generator_panel
from utils.session_state import init_state

init_state()
st.title("👥 Customers")
st.caption("Customers live in PostgreSQL. Select one to inspect and edit their records, or start a voice call.")
try:
    customers = client.list_customers()
except client.ApiError as e:
    st.error(str(e))
    st.stop()

t_dir, t_add, t_demo = st.tabs(["Directory", "➕ Add customer", "🧪 Demo data"])
with t_dir:
    a, b = st.columns([3, 1])
    q = a.text_input("Search by name, ID, mobile or city", "", label_visibility="collapsed", placeholder="Search by name, ID, mobile or city")
    show = b.selectbox("Status", ["All", "Active", "Inactive"], label_visibility="collapsed")
    rows = customers
    if q:
        ql = q.lower()
        rows = [c for c in rows if ql in " ".join(str(v) for v in c.values()).lower()]
    if show != "All":
        rows = [c for c in rows if (c["status"] == "inactive") == (show == "Inactive")]
    st.caption(f"{len(rows)} customer(s)")
    cols = st.columns(3)
    for i, c in enumerate(rows):
        with cols[i % 3]:
            customer_card(c)
with t_add:
    st.write("Add a customer manually. Email and mobile must be unique; address needs a 6-digit PIN code.")
    add_customer_form()
    if st.session_state.selected_customer and st.button("Open the new customer"):
        st.switch_page("pages/customer_dashboard.py")
with t_demo:
    demo_generator_panel(customers)
