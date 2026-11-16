import pandas as pd
import streamlit as st

import ui
from app.intelligence.recurring import analyze

ui.setup("Root-cause insights", "🔎")
df, inc = ui.data()

st.caption("Auto-generated from the ticket data: what recurs, where and when, with a plain-English recommended next step.")
insights = analyze(df, inc)
order = {"high": 0, "medium": 1, "low": 2}
for i in sorted(insights, key=lambda x: order[x.severity]):
    icon = {"high": "🔴", "medium": "🟠", "low": "🟡"}[i.severity]
    with st.container(border=True):
        st.markdown(f"#### {icon} {i.title}")
        st.markdown(f"**What we see:** {i.finding}")
        st.markdown(f"**Recommended action:** {i.recommendation}")
ui.export(pd.DataFrame([{"title": i.title, "severity": i.severity, "finding": i.finding, "recommendation": i.recommendation} for i in insights]), "insights")
