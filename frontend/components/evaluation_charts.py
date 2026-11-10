import pandas as pd
import streamlit as st


def metric_chart(summary: dict) -> None:
    m = summary.get("metrics", {})
    if m:
        st.bar_chart(pd.DataFrame({"score (1-5)": m}), horizontal=True)


def category_chart(summary: dict) -> None:
    cats = summary.get("by_category", {})
    if cats:
        st.bar_chart(pd.DataFrame({"pass rate": {k: v["pass_rate"] for k, v in cats.items()}}))
