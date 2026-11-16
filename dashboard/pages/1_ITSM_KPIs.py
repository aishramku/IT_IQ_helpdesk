import plotly.express as px
import streamlit as st

import ui
from app.constants import SLA_HOURS

ui.setup("ITSM KPIs", "📊")
df, inc = ui.data()
k = ui.kpi(df, inc)

st.info("SLA targets (resolution, calendar hours): " + " | ".join(f"**{p}** {h}h" for p, h in SLA_HOURS.items()) +
        ".  Major-incident children are linked to their parent and counted **once** (as the parent P1) so P1 breach rates aren't inflated.")

c = st.columns(4)
c[0].metric("Tickets in KPI scope", f"{len(k):,}")
c[1].metric("Overall SLA breach rate", f"{k.breached.mean():.1%}")
c[2].metric("Median resolution (h)", f"{k.resolution_hours.median():.1f}")
fcr = (k.reassignment_count == 0).mean()
c[3].metric("First-contact resolution", f"{fcr:.1%}", help="Resolved without any reassignment between teams (baseline history)")

l, r = st.columns(2)
with l:
    st.subheader("MTTR by category (hours)")
    m = k.groupby("category").resolution_hours.agg(mean="mean", median="median", tickets="size").round(1).reset_index()
    fig = px.bar(m, x="category", y=["mean", "median"], barmode="group", color_discrete_sequence=["#4C78A8", "#F58518"])
    st.plotly_chart(fig)
    ui.export(m, "mttr_by_category")
with r:
    st.subheader("SLA breach rate by priority")
    b = k.groupby("kpi_priority").agg(breach_rate=("breached", "mean"), tickets=("breached", "size")).reset_index().sort_values("kpi_priority")
    b["sla_hours"] = b.kpi_priority.map(SLA_HOURS)
    fig = px.bar(b, x="kpi_priority", y="breach_rate", text=b.breach_rate.map("{:.0%}".format), color="kpi_priority", color_discrete_map=ui.PRIO_COLORS)
    fig.update_layout(yaxis_tickformat=".0%", showlegend=False, xaxis_title="priority")
    st.plotly_chart(fig)
    st.dataframe(b.rename(columns={"kpi_priority": "priority"}), hide_index=True)
    ui.export(b, "sla_breach_by_priority")

st.subheader("First-contact resolution by category")
f = k.groupby("category").apply(lambda g: (g.reassignment_count == 0).mean(), include_groups=False).reset_index(name="fcr")
st.plotly_chart(px.bar(f, x="category", y="fcr", text=f.fcr.map("{:.0%}".format), color="category", color_discrete_map=ui.CAT_COLORS)
                .update_layout(yaxis_tickformat=".0%", showlegend=False))
