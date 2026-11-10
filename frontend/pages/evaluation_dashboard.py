import time

import pandas as pd
import streamlit as st

from api import client
from components.evaluation_charts import category_chart, metric_chart
from utils.session_state import init_state

init_state()
st.title("📊 Evaluation Dashboard")
DATASETS = ["customer_support_cases", "order_queries", "refund_queries", "multilingual_queries", "adversarial_queries"]
with st.expander("Run a new evaluation", expanded=False):
    ds = st.multiselect("Datasets", DATASETS, default=DATASETS)
    mc = st.number_input("Max cases (0 = all)", 0, 500, 0)
    judge = st.toggle("Use LLM-as-a-Judge", value=True)
    if st.button("Run evaluation", type="primary"):
        try:
            r = client.run_evaluation(ds, int(mc) or None, judge)
            bar = st.progress(0.0, "Running…")
            while True:
                s = client.get_evaluation(r["evaluation_id"])
                bar.progress(min(1.0, s["progress"]), "Running…")
                if s["status"] in ("completed", "failed"):
                    break
                time.sleep(2)
            st.session_state.last_eval = r["evaluation_id"]
            st.success(s["status"]) if s["status"] == "completed" else st.error(s.get("error"))
        except client.ApiError as e:
            st.error(str(e))

try:
    runs = [e for e in client.list_evaluations() if e["status"] == "completed"]
except client.ApiError as e:
    st.error(str(e))
    st.stop()
if not runs:
    st.info("No completed evaluations yet. Run one above, or `python -m app.evaluation.run_evaluation` from /backend.")
    st.stop()
ids = [r["evaluation_id"] for r in runs]
sel = st.selectbox("Report", ids, index=ids.index(st.session_state.last_eval) if st.session_state.last_eval in ids else 0)
rep = client.get_evaluation(sel)["report"]
s = rep["summary"]
cfg = rep["config"]
st.caption(f"Response model: {cfg['response_model']} · Judge: {cfg['judge_model'] or 'off (deterministic only)'}")
c = st.columns(5)
c[0].metric("Overall score", s["overall_score"])
c[1].metric("Pass rate", f"{s['pass_rate']:.0%}")
c[2].metric("Hallucination rate", f"{s['hallucination_rate']:.0%}")
c[3].metric("Tool accuracy", f"{s['tool_selection_accuracy']:.0%}")
c[4].metric("p95 latency", f"{s['latency_ms']['p95']:.0f} ms")
c = st.columns(4)
c[0].metric("Intent accuracy", f"{(s['intent_accuracy'] or 0):.0%}")
c[1].metric("Action correctness", f"{(s['action_correctness'] or 0):.0%}")
c[2].metric("Customer isolation", f"{(s['ownership_isolation'] or 0):.0%}")
c[3].metric("Avg latency", f"{s['latency_ms']['avg']:.0f} ms")
l, r = st.columns(2)
with l:
    st.markdown("**Metric scores (1–5)**")
    metric_chart(s)
with r:
    st.markdown("**Pass rate by category**")
    category_chart(s)
st.markdown("### Cases")
only_failed = st.toggle("Only failed", value=True)
cases = [x for x in rep["cases"] if not (only_failed and x["passed"])]
st.dataframe(pd.DataFrame([{"ID": x["test_id"], "Dataset": x["dataset"], "Category": x["category"], "Pass": x["passed"],
                            "Why failed": x["failure_reason"], "Latency ms": (x["latencies_ms"] or [0])[-1]} for x in cases]),
             use_container_width=True, hide_index=True)
pick = st.selectbox("Inspect case", [x["test_id"] for x in rep["cases"]])
x = next(i for i in rep["cases"] if i["test_id"] == pick)
st.write("**Query:**", " → ".join(x["queries"]))
st.write("**Expected behaviour:**", x.get("expected_behavior"))
st.write("**Agent reply:**", x["response"])
st.write("**Tools called:**", ", ".join(x["tools"]) or "—")
st.write("**Scores:**", x["scores"])
st.write("**Hard checks:**", x["hard_checks"], "· action:", x.get("action_detail"))
if x.get("judge"):
    j = x["judge"]
    st.markdown(f"**Judge:** pass={j['overall_pass']} · hallucination={j['hallucination']} · category={j['failure_category']}")
    st.write(j["explanation"])
    st.write("Evidence:", j["evidence"])
