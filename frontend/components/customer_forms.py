"""Forms and panels for editing customers: profile, order delivery address, add customer, demo data, status, change log."""
import pandas as pd
import streamlit as st

from api import client

LANG_OPTIONS = {"English": "en-IN", "Hindi": "hi-IN", "Marathi": "mr-IN", "Hinglish": "hinglish", "Tamil": "ta-IN",
                "Telugu": "te-IN", "Kannada": "kn-IN", "Malayalam": "ml-IN", "Bengali": "bn-IN", "Gujarati": "gu-IN",
                "Punjabi": "pa-IN"}
CODE_TO_LABEL = {v: k for k, v in LANG_OPTIONS.items()}
EDITABLE = {"placed", "processing"}


def _err(e: Exception) -> None:
    st.error(str(e).split(": ", 1)[-1])


def status_badge(status: str) -> str:
    return f'<span class="badge {"on" if status == "active" else "off"}">{status}</span>'


def status_controls(profile: dict) -> None:
    """Activate / deactivate (with an explicit confirmation step)."""
    cid, active = profile["customer_id"], profile["status"] != "inactive"
    c1, c2 = st.columns([1, 3])
    c1.markdown(status_badge(profile["status"]), unsafe_allow_html=True)
    if active:
        with c2.popover("Deactivate customer"):
            st.write("A deactivated customer cannot start new support calls and any open call is ended. Records are kept.")
            if st.button("Yes, deactivate", key=f"deact_{cid}", type="primary"):
                try:
                    client.deactivate_customer(cid)
                    st.rerun()
                except client.ApiError as e:
                    _err(e)
    elif c2.button("Reactivate customer", key=f"act_{cid}"):
        try:
            client.activate_customer(cid)
            st.rerun()
        except client.ApiError as e:
            _err(e)


def _address_inputs(addr: dict, key: str) -> dict:
    a, b = st.columns(2)
    line1 = a.text_input("Address line 1", addr.get("line1") or "", key=f"{key}_l1")
    line2 = b.text_input("Address line 2 (optional)", addr.get("line2") or "", key=f"{key}_l2")
    c, d, e = st.columns(3)
    city = c.text_input("City", addr.get("city") or "", key=f"{key}_city")
    state = d.text_input("State", addr.get("state") or "", key=f"{key}_state")
    pin = e.text_input("PIN code (6 digits)", addr.get("postal_code") or "", key=f"{key}_pin", max_chars=6)
    return {"line1": line1, "line2": line2, "city": city, "state": state, "postal_code": pin}


def profile_form(profile: dict) -> None:
    cid = profile["customer_id"]
    ver = st.session_state.setdefault(f"ver_{cid}", 0)
    key = f"pf_{cid}_{ver}"
    with st.form(key):
        c1, c2 = st.columns(2)
        name = c1.text_input("Full name", profile["full_name"])
        email = c2.text_input("Email", profile["email"])
        c3, c4 = st.columns(2)
        mobile = c3.text_input("Mobile (10 digits)", profile["mobile_number"])
        label = CODE_TO_LABEL.get(profile.get("preferred_language"), "English")
        lang = c4.selectbox("Preferred language", list(LANG_OPTIONS), index=list(LANG_OPTIONS).index(label))
        st.markdown("**Address**")
        addr = _address_inputs(profile.get("address") or {}, key)
        go = st.form_submit_button("Save changes", type="primary")
    if not go:
        return
    cur = profile.get("address") or {}
    payload: dict = {}
    if name.strip() != profile["full_name"]:
        payload["full_name"] = name
    if email.strip().lower() != profile["email"].lower():
        payload["email"] = email
    if "".join(ch for ch in mobile if ch.isdigit())[-10:] != "".join(ch for ch in profile["mobile_number"] if ch.isdigit())[-10:]:
        payload["mobile_number"] = mobile
    if LANG_OPTIONS[lang] != profile.get("preferred_language"):
        payload["preferred_language"] = LANG_OPTIONS[lang]
    changed_addr = {k: val for k, val in addr.items() if (val or "") != (cur.get(k) or "")}
    if changed_addr:
        payload["address"] = addr
    if not payload:
        st.info("Nothing changed.")
        return
    try:
        client.update_customer(cid, payload)
        st.session_state[f"ver_{cid}"] = ver + 1
        st.toast("Profile updated ✅")
        st.rerun()
    except client.ApiError as e:
        _err(e)


def order_address_panel(customer_id: str, orders: list[dict]) -> None:
    editable = [o for o in orders if o["order_status"] in EDITABLE]
    locked = [o for o in orders if o["order_status"] not in EDITABLE]
    if not editable:
        st.info("None of this customer's orders can be edited: the delivery address can only change before dispatch "
                "(status placed or processing).")
    else:
        oid = st.selectbox("Order", [o["order_id"] for o in editable],
                           format_func=lambda x: f"{x} · " + ", ".join(i["product_name"] for i in next(o for o in editable if o["order_id"] == x)["items"]))
        order = next(o for o in editable if o["order_id"] == oid)
        ver = st.session_state.setdefault(f"overs_{oid}", 0)
        key = f"oa_{oid}_{ver}"
        st.caption(f"Status: {order['order_status']} · can be changed until the order is dispatched.")
        with st.form(key):
            addr = _address_inputs(order.get("shipping_address") or {}, key)
            go = st.form_submit_button("Update delivery address", type="primary")
        if go:
            try:
                client.update_order_address(oid, customer_id, addr)
                st.session_state[f"overs_{oid}"] = ver + 1
                st.toast("Delivery address updated ✅")
                st.rerun()
            except client.ApiError as e:
                _err(e)
    if locked:
        with st.expander(f"Orders that can no longer be edited ({len(locked)})"):
            st.dataframe(pd.DataFrame([{"Order": o["order_id"], "Status": o["order_status"],
                                        "Reason": "Already dispatched/closed"} for o in locked]),
                         use_container_width=True, hide_index=True)


def add_customer_form() -> None:
    with st.form("add_customer", clear_on_submit=False):
        c1, c2 = st.columns(2)
        name = c1.text_input("Full name")
        email = c2.text_input("Email")
        c3, c4 = st.columns(2)
        mobile = c3.text_input("Mobile (10 digits)")
        lang = c4.selectbox("Preferred language", list(LANG_OPTIONS))
        addr = _address_inputs({}, "add")
        go = st.form_submit_button("Create customer", type="primary")
    if go:
        try:
            c = client.create_customer({"full_name": name, "email": email, "mobile_number": mobile,
                                        "preferred_language": LANG_OPTIONS[lang], "address": addr})
            st.success(f"Created {c['customer_id']} — {c['full_name']}")
            st.session_state.selected_customer = c["customer_id"]
        except client.ApiError as e:
            _err(e)


def demo_generator_panel(customers: list[dict]) -> None:
    st.write("Create dummy customers (with sample orders and payments) to test the agent. They are marked as test data "
             "and can be deleted again; the 15 seeded customers are protected.")
    c1, c2, c3 = st.columns([1, 1, 1])
    n = c1.number_input("How many", 1, 25, 3)
    with_orders = c2.toggle("Include orders + payments", value=True)
    if c3.button("Generate demo customers", type="primary", use_container_width=True):
        try:
            res = client.generate_demo(int(n), with_orders)
            st.success(f"Created {res['count']} customers")
            st.dataframe(pd.DataFrame(res["created"]), use_container_width=True, hide_index=True)
        except client.ApiError as e:
            _err(e)
    seeded = {f"CUS{1000 + i}" for i in range(1, 16)}
    test = [c for c in customers if c["customer_id"] not in seeded]
    if test:
        st.markdown("**Test customers**")
        for c in test:
            a, b = st.columns([4, 1])
            a.write(f"`{c['customer_id']}` {c['full_name']} · {c['mobile_number']} · {c['total_orders']} orders · {c['status']}")
            if b.button("Delete", key=f"del_{c['customer_id']}"):
                try:
                    client.delete_customer(c["customer_id"])
                    st.rerun()
                except client.ApiError as e:
                    _err(e)


def changelog_table(rows: list[dict], key: str, show_customer: bool = True) -> None:
    if not rows:
        st.info("No changes recorded yet.")
        return
    df = pd.DataFrame(rows)
    df["created_at"] = df["created_at"].str.replace("T", " ").str[:19]
    cols = ["created_at"] + (["customer_id"] if show_customer else []) + ["entity_type", "entity_id", "field", "old_value",
                                                                          "new_value", "source", "actor"]
    st.dataframe(df[cols], use_container_width=True, hide_index=True)
    st.download_button("Download CSV", df[cols].to_csv(index=False).encode("utf-8"), file_name="change_log.csv",
                       mime="text/csv", key=f"dl_{key}")
