import plotly.express as px
import streamlit as st

import ui
from app.analytics import audit_df
from app.models import AuditLog  # noqa: F401  (schema reference)

ui.setup("Major Incidents", "🚨")
df, inc = ui.data()

if inc.empty:
    st.info("No major incidents detected yet.")
    st.stop()

st.caption("Rule: >= 10 DISTINCT requesters reporting a similar issue (same category, text similarity) within a 15-minute sliding window -> P1 incident; "
           "child tickets are linked and re-prioritised with an audit entry. Duplicates are merged first so one user cannot trigger an incident.")
show = inc[["incident_id", "title", "category", "priority", "status", "detected_at", "window_start", "window_end", "resolved_at", "ticket_count", "distinct_requesters"]].copy()
show["time_to_resolve_h"] = ((inc.resolved_at - inc.window_start).dt.total_seconds() / 3600).round(2)
show["detection_lag_min"] = ((inc.detected_at - inc.window_start).dt.total_seconds() / 60).round(1)
st.dataframe(show, hide_index=True)
ui.export(show, "incidents")

sel = st.selectbox("Inspect incident", inc.incident_id.tolist())
row = inc[inc.incident_id == sel].iloc[0]
kids = df[df.incident_id == sel].sort_values("created_at")
c = st.columns(4)
c[0].metric("Linked tickets", len(kids))
c[1].metric("Distinct requesters", int(row.distinct_requesters))
c[2].metric("Detected after", f"{(row.detected_at - row.window_start).total_seconds() / 60:.0f} min")
c[3].metric("Resolved after", f"{(row.resolved_at - row.window_start).total_seconds() / 3600:.1f} h" if row.resolved_at == row.resolved_at else "open")

st.subheader("Timeline of linked tickets")
kids = kids.assign(n=range(1, len(kids) + 1))
fig = px.scatter(kids, x="created_at", y="n", hover_data=["ticket_id", "requester_email", "subject"], labels={"n": "cumulative tickets", "created_at": ""})
fig.add_vline(x=row.detected_at, line_dash="dash", line_color="#C0392B", annotation_text="incident declared")
if row.resolved_at == row.resolved_at:
    fig.add_vline(x=row.resolved_at, line_dash="dot", line_color="#54A24B", annotation_text="resolved")
st.plotly_chart(fig)

st.subheader("Linked tickets")
st.dataframe(kids[["ticket_id", "created_at", "requester_email", "location", "subject", "initial_priority", "priority", "status"]], hide_index=True)
ui.export(kids.drop(columns=["clean_text", "n"]), f"{sel}_tickets")

st.subheader("Re-prioritisation audit trail")
a = audit_df(50000)
a = a[(a.step == "reprioritisation") & a.ticket_id.isin(kids.ticket_id)][["ts", "ticket_id", "decision", "reason"]]
st.dataframe(a.head(100), hide_index=True)
