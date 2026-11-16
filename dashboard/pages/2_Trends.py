import plotly.express as px
import streamlit as st

import ui

ui.setup("Trends", "📈")
df, inc = ui.data()
df = df[~df.is_malicious.astype(bool)]
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

cats = st.multiselect("Categories", sorted(df.category.dropna().unique()), default=sorted(df.category.dropna().unique()))
d = df[df.category.isin(cats)]

st.subheader("Volume by day of week and hour")
h = d.groupby(["dow", "hour"]).size().unstack(fill_value=0).reindex(index=range(7), columns=range(24), fill_value=0)
fig = px.imshow(h.values, x=list(range(24)), y=DOW, aspect="auto", color_continuous_scale="Blues", labels=dict(x="hour of day", y="", color="tickets"))
st.plotly_chart(fig)
st.caption("Look for the Monday 09:00-11:00 block: that is the VPN-driven peak the root-cause page explains.")

st.subheader("Category trend (weekly)")
w = d.assign(week=d.created_at.dt.to_period("W").dt.start_time).groupby(["week", "category"]).size().reset_index(name="tickets")
st.plotly_chart(px.line(w, x="week", y="tickets", color="category", markers=True, color_discrete_map=ui.CAT_COLORS))

l, r = st.columns(2)
with l:
    st.subheader("Incident vs Service Request over time")
    t = d.assign(week=d.created_at.dt.to_period("W").dt.start_time).groupby(["week", "ticket_type"]).size().reset_index(name="tickets")
    st.plotly_chart(px.area(t, x="week", y="tickets", color="ticket_type", color_discrete_map={"Incident": "#E45756", "Service Request": "#4C78A8"}))
with r:
    st.subheader("Tickets by location")
    loc = d.groupby(["location", "category"]).size().reset_index(name="tickets")
    st.plotly_chart(px.bar(loc, x="location", y="tickets", color="category", color_discrete_map=ui.CAT_COLORS))

ui.export(h.reset_index().rename(columns={"dow": "day_of_week"}), "volume_heatmap")
ui.export(w, "category_weekly_trend")
