import pandas as pd
import plotly.express as px
import streamlit as st

import ui
from app.analytics import audit_df

ui.setup("Security", "🛡️")
df, inc = ui.data()
m = ui.metrics()
flag = df[df.security_flag.notna()]

c = st.columns(4)
c[0].metric("Flagged tickets", len(flag))
c[1].metric("Social engineering", int((flag.security_flag == "social_engineering").sum()))
c[2].metric("Prompt injection blocked", int((flag.security_flag == "prompt_injection").sum()))
c[3].metric("Auto-executed account actions", 0, help="By design the system never executes resets, unlocks, grants or installs")

st.info("Guardrails: suspicious tickets go to **Security Review** and are never auto-assigned; ticket text can't set priority; "
        "password resets only produce `verification_required`; account/access actions require approval.")

l, r = st.columns(2)
with l:
    st.subheader("Flagged by sender type")
    st.plotly_chart(px.histogram(flag, x="security_flag", color=flag.sender_domain.where(~flag.sender_domain.eq("acmecorp.com"), "acmecorp.com (internal)"),
                                 labels={"color": "sender domain"}))
with r:
    st.subheader("Action tiers on all tickets")
    t = df.action_status.value_counts().reset_index()
    t.columns = ["action_status", "tickets"]
    st.plotly_chart(px.bar(t, x="tickets", y="action_status", orientation="h"))

st.subheader("Flagged tickets")
cols = ["ticket_id", "created_at", "requester_email", "sender_domain", "subject", "security_flag", "security_score", "priority", "routed_queue", "action_status"]
st.dataframe(flag.sort_values("created_at", ascending=False)[cols], hide_index=True)
ui.export(flag[cols], "security_flagged_tickets")

st.subheader("Detector quality (evaluated against hidden labels)")
sec = m.get("security", {})
if sec:
    rows = []
    for k, label in (("social_engineering", "Social engineering"), ("prompt_injection", "Prompt injection"), ("combined", "Either")):
        s = sec[k]
        rows.append({"detector": label, "precision": s["precision"], "recall": s["recall"], "false-positive rate (legit tickets)": s["false_positive_rate_on_legitimate"],
                     "TP": s["tp"], "FP": s["fp"], "FN": s["fn"], "legit tickets": s["n_legitimate"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    st.caption(f"Includes {sec['n_decoys']} legitimate decoys (urgent real executives, 'please ignore my previous ticket'). "
               f"Decoys wrongly flagged: {len(sec['decoy_false_positives'])}. Missed attacks: {len(sec['missed'])}. "
               "⚠ The attack tickets and the detector rules were written by the same author, so these numbers are optimistic; "
               "a real deployment needs an independently collected attack set.")

st.subheader("Security audit trail")
a = audit_df(60000)
a = a[a.step == "security"][a.decision != "screen_clear"][["ts", "ticket_id", "decision", "reason"]]
st.dataframe(a.head(200), hide_index=True)
ui.export(a, "security_audit")
