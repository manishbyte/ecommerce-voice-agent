import pandas as pd
import streamlit as st


def orders_table(orders: list[dict]) -> None:
    if not orders:
        st.info("No orders.")
        return
    st.dataframe(pd.DataFrame([{
        "Order": o["order_id"], "Date": o["order_date"], "Status": o["order_status"], "Total (₹)": o["total_amount"],
        "ETA": o["estimated_delivery_date"], "Delivered": o["delivered_at"], "Carrier": o["carrier"],
        "Tracking": o["tracking_number"], "Items": ", ".join(f"{i['product_name']} ×{i['quantity']}" for i in o["items"])}
        for o in orders]), use_container_width=True, hide_index=True)
