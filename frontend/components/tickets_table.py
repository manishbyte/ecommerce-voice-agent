import pandas as pd
import streamlit as st


def tickets_table(tickets: list[dict]) -> None:
    if not tickets:
        st.info("No support tickets.")
        return
    st.dataframe(pd.DataFrame(tickets).drop(columns=["customer_id"], errors="ignore"), use_container_width=True, hide_index=True)
