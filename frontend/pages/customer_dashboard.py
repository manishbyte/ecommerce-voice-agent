import streamlit as st

from api import client
from components.customer_forms import changelog_table, order_address_panel, profile_form, status_controls
from components.customer_profile import customer_profile
from components.orders_table import orders_table
from components.payments_table import payments_table
from components.tickets_table import tickets_table
from utils.session_state import init_state

init_state()
cid = st.session_state.selected_customer
st.title("🧾 Customer Dashboard")
if not cid:
    st.info("Select a customer from the Customers page first.")
    st.stop()
try:
    d = client.customer_detail(cid)
except client.ApiError as e:
    st.error(str(e))
    st.stop()
top_l, top_r = st.columns([3, 2])
with top_l:
    customer_profile(d["profile"])
with top_r:
    status_controls(d["profile"])
    if d["profile"]["status"] == "inactive":
        st.caption("Deactivated customers cannot start voice calls.")
    elif st.button("🎙️ Start voice support for this customer", type="primary", use_container_width=True):
        st.switch_page("pages/voice_support.py")

t1, t2, t3, t4, t5, t6, t7 = st.tabs([f"Orders ({len(d['orders'])})", f"Payments & refunds ({len(d['payments'])}/{len(d['refunds'])})",
                                      f"Tickets ({len(d['tickets'])})", "Products in orders", "✏️ Edit profile",
                                      "📦 Edit delivery address", "🕘 Change log"])
with t1:
    orders_table(d["orders"])
with t2:
    payments_table(d["payments"], d["refunds"])
with t3:
    tickets_table(d["tickets"])
with t4:
    rows = {i["product_id"]: i for o in d["orders"] for i in o["items"]}
    st.dataframe([{"Product": v["product_id"], "Name": v["product_name"], "Unit price (₹)": v["unit_price"]} for v in rows.values()],
                 use_container_width=True, hide_index=True)
with t5:
    st.caption("Changes are validated (email format, 10-digit mobile, 6-digit PIN) and recorded in the change log.")
    profile_form(d["profile"])
with t6:
    order_address_panel(cid, d["orders"])
with t7:
    try:
        changelog_table(client.customer_changes(cid), key=f"c_{cid}", show_customer=False)
    except client.ApiError as e:
        st.error(str(e))
