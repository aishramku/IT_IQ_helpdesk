"""Overview page.   streamlit run dashboard/Home.py"""
import plotly.express as px
import streamlit as st

import ui
from app.analytics import audit_df, overview
from app.intelligence.impact import before_after

ui.setup("Overview", "🎫")
df, inc = ui.data()
o = overview(df, inc)

st.caption("Synthetic 90-day helpdesk history processed by the TriageIQ pipeline (clean -> classify -> prioritise -> route -> KB -> incident detection). "
           "Tiles below cover ALL history; ~80% of it trained the model, so routing figures are optimistic - the before/after section defaults to held-out tickets.")
c = st.columns(5)
c[0].metric("Total tickets", f"{o['total']:,}")
c[1].metric("Open / in progress", f"{o['open']:,}", help="Not resolved and not merged as a duplicate")
c[2].metric("Resolved", f"{o['resolved']:,}")
c[3].metric("Auto-routed", f"{o['auto_routed_pct']:.1%}", help="Confidence >= threshold and no security flag")
c[4].metric("Needs Review", f"{o['needs_review_pct']:.1%}", help="Below the confidence threshold: human-in-the-loop queue")
c = st.columns(5)
c[0].metric("Deflection rate", f"{o['deflection_rate']:.1%}", help="Share of tickets resolved by the user via a self-service KB article")
c[1].metric("KB article suggested", f"{o['kb_suggested_pct']:.1%}")
c[2].metric("Security Review", o["security_review"], help="Suspicious tickets held back from automation")
c[3].metric("Major incidents", o["incidents"])
c[4].metric("Merged duplicates", o["merged"])

left, right = st.columns(2)
with left:
    st.subheader("Incident vs Service Request (ITIL)")
    t = df.ticket_type.value_counts().reset_index()
    t.columns = ["ticket_type", "tickets"]
    st.plotly_chart(px.pie(t, names="ticket_type", values="tickets", hole=0.55, color="ticket_type",
                           color_discrete_map={"Incident": "#E45756", "Service Request": "#4C78A8"}))
    st.caption("Incidents = something is broken (restore service). Service Requests = standard asks (password reset, access, install).")
with right:
    st.subheader("Where tickets were routed")
    q = df.routed_queue.value_counts().reset_index()
    q.columns = ["queue", "tickets"]
    st.plotly_chart(px.bar(q, x="tickets", y="queue", orientation="h", text="tickets"))

st.subheader("Before vs after: routing quality")
scope = st.radio("Evaluate on", ["Held-out tickets (never seen in training) - honest", "All history - optimistic, ~80% was used to train the model"],
                 horizontal=True)
ev = ui.heldout(df) if scope.startswith("Held") else df
ba, oe = before_after(ev), overview(ev, inc)
b = st.columns(5)
b[0].metric("Baseline misroute rate (manual L1)", f"{ba['baseline_misroute_rate']:.1%}")
b[1].metric("Pipeline misroute rate (auto-routed)", f"{ba['pipeline_misroute_rate_of_auto']:.1%}",
            help="Auto-assigned tickets that went to the wrong team. Includes label-noise cases in the history.")
b[2].metric("Auto-routed / Needs Review", f"{oe['auto_routed_pct']:.0%} / {oe['needs_review_pct']:.0%}")
b[3].metric("Misroutes avoided", f"{ba['misroutes_avoided']:,}")
b[4].metric("Reassignments saved", f"{ba['reassignments_saved']:,.0f}", help="Estimated using the baseline average reassignments per misroute")
st.caption(f"Compared on {ba['tickets']:,} tickets: baseline = team the human L1 first assigned; pipeline = team auto-assigned; truth = team that resolved it. "
           f"{ba['needs_review']:,} tickets ({ba['needs_review_pct']:.1%}) went to Needs Review and are not counted as misroutes (a human decides).")

with st.expander("Export datasets (Power BI)"):
    ui.export(df.drop(columns=["clean_text"]), "tickets", "tickets")
    ui.export(inc, "incidents", "incidents")
    ui.export(audit_df(20000), "audit_log", "audit log (latest 20k)")
