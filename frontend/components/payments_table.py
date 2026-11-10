import pandas as pd
import streamlit as st


def payments_table(payments: list[dict], refunds: list[dict] | None = None) -> None:
    if payments:
        st.dataframe(pd.DataFrame(payments).drop(columns=["customer_id", "currency"], errors="ignore"),
                     use_container_width=True, hide_index=True)
    else:
        st.info("No payments.")
    if refunds:
        st.markdown("**Refunds**")
        st.dataframe(pd.DataFrame(refunds).drop(columns=["customer_id", "currency"], errors="ignore"),
                     use_container_width=True, hide_index=True)
