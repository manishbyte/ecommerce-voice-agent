import streamlit as st

from api import client
from components.customer_forms import changelog_table
from utils.session_state import init_state

init_state()
st.title("🕘 Change Log")
st.caption("Every edit — from the dashboard or confirmed by voice — with the old and new value.")
try:
    rows = client.all_changes(1000)
except client.ApiError as e:
    st.error(str(e))
    st.stop()
a, b, c = st.columns(3)
who = a.selectbox("Customer", ["All"] + sorted({r["customer_id"] for r in rows}))
src = b.selectbox("Source", ["All"] + sorted({r["source"] for r in rows}))
fld = c.selectbox("Field", ["All"] + sorted({r["field"] for r in rows}))
rows = [r for r in rows if (who == "All" or r["customer_id"] == who) and (src == "All" or r["source"] == src)
        and (fld == "All" or r["field"] == fld)]
st.caption(f"{len(rows)} change(s)")
changelog_table(rows, key="all")
