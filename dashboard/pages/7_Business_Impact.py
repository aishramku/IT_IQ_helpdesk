import pandas as pd
import streamlit as st

import ui
from app.analytics import overview
from app.intelligence.impact import before_after

ui.setup("Business impact calculator", "💰")
df, inc = ui.data()
ho = ui.heldout(df)  # rates come from tickets the model never saw in training
o, ba = overview(df, inc), before_after(ho)
o_h = overview(ho, inc)
days = max((df.created_at.max() - df.created_at.min()).days, 1)
monthly_default = int(len(df) / days * 30)

st.caption("All figures are ESTIMATES driven by the sliders below and by rates measured on the synthetic history. Change the assumptions to match your helpdesk.")
a, b = st.columns(2)
with a:
    volume = st.number_input("Tickets per month", 100, 100000, monthly_default, step=100)
    handle = st.slider("Average handling time per ticket (minutes)", 5, 60, 20)
    cost = st.slider("Hourly agent cost (INR)", 150, 2000, 450, step=25)
with b:
    triage_share = st.slider("Share of handling time spent on manual triage/routing", 5, 50, 25, help="Reading, categorising, prioritising, assigning") / 100
    reassign_min = st.slider("Minutes lost per reassignment (hand-off, re-read, wait)", 5, 60, 20)
    review_min = st.slider("Human time per 'Needs Review' ticket (minutes)", 1, 15, 3)
    uplift = st.slider("Extra tickets deflected by KB suggestions (% of volume)", 0, 15, 3) / 100

auto = o_h["auto_routed_pct"]
review = o_h["needs_review_pct"]
reassign_saved_per_ticket = ba["reassignments_saved"] / ba["tickets"]
dup_rate = o["merged"] / o["total"]
inc_children = (inc.ticket_count.sum() - len(inc)) / o["total"] if len(inc) else 0

rows = [
    ("Automatic triage & routing", volume * auto * handle * triage_share / 60, f"{auto:.1%} auto-routed x {handle} min x {triage_share:.0%} triage share"),
    ("Fewer misroutes / reassignments", volume * reassign_saved_per_ticket * reassign_min / 60, f"{reassign_saved_per_ticket:.3f} reassignments saved per ticket x {reassign_min} min"),
    ("KB deflection uplift", volume * uplift * handle / 60, f"{uplift:.0%} of tickets resolved without an agent x {handle} min"),
    ("Duplicates merged", volume * dup_rate * handle * 0.5 / 60, f"{dup_rate:.1%} of tickets merged x 50% of handling time"),
    ("Incident children handled once", volume * inc_children * handle * 0.5 / 60, f"{inc_children:.2%} of tickets linked to a parent x 50% of handling time"),
    ("LESS: human review of low-confidence tickets", -volume * review * review_min / 60, f"{review:.1%} Needs Review x {review_min} min"),
]
t = pd.DataFrame(rows, columns=["component", "hours_saved_per_month", "assumption"])
t["inr_per_month"] = t.hours_saved_per_month * cost
total_h, total_c = t.hours_saved_per_month.sum(), t.inr_per_month.sum()

c = st.columns(4)
c[0].metric("Hours saved / month", f"{total_h:,.0f}")
c[1].metric("Cost saved / month", f"₹{total_c:,.0f}")
c[2].metric("Cost saved / year", f"₹{total_c * 12:,.0f}")
c[3].metric("FTE equivalent", f"{total_h / 160:.1f}", help="160 working hours per FTE-month")
st.dataframe(t.round(1), hide_index=True)
ui.export(t, "business_impact")

st.subheader("Assumptions in plain English")
st.markdown(f"""
- Routing rates (auto-routed **{auto:.1%}**, needs-review **{review:.1%}**, misroute reduction) are **measured on {len(ho):,} held-out tickets** the model never trained on; duplicate/incident rates (**{dup_rate:.1%}** merged) use all {len(df):,} synthetic tickets.
- Handling time, hourly cost, triage share, minutes per reassignment, review time and KB uplift are **your assumptions** (sliders).
- Baseline manual misroute rate **{ba['baseline_misroute_rate']:.1%}** vs pipeline **{ba['pipeline_misroute_rate_of_auto']:.1%}** on auto-routed tickets; savings count only tickets the pipeline routed automatically.
- Savings are *time freed*, not headcount removed. Nothing here assumes security-flagged or approval-gated actions are automated.
""")
