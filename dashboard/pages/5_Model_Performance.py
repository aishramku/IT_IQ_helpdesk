import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import ui
from app.analytics import feedback_df

ui.setup("Model performance", "🧠")
df, inc = ui.data()
m = ui.metrics()
if not m:
    st.warning("Run `python -m ml.train` and `python -m ml.evaluate` first.")
    st.stop()

st.caption(f"Model `{m['model_version']}` - metrics are on a **held-out test set** ({m['n_test']} tickets never seen in training). "
           "The synthetic history has ~5% deliberate label noise, so ~95% is a practical ceiling.")
c = st.columns(5)
c[0].metric("Category accuracy", f"{m['accuracy']:.1%}")
c[1].metric("Macro F1", f"{m['macro_f1']:.3f}")
c[2].metric("Ticket-type accuracy", f"{m['ticket_type_accuracy']:.1%}")
c[3].metric("Priority exact / within 1", f"{m['priority']['exact']:.0%} / {m['priority']['within_one']:.0%}")
c[4].metric("KB top-1 hit rate", f"{m['kb_hit_rate']:.0%}")

l, r = st.columns(2)
with l:
    st.subheader("Confusion matrix")
    cm = pd.DataFrame(m["confusion_matrix"], index=m["labels"], columns=m["labels"])
    st.plotly_chart(px.imshow(cm, text_auto=True, color_continuous_scale="Blues", labels=dict(x="predicted", y="true")))
with r:
    st.subheader("Per-class precision / recall")
    pc = pd.DataFrame(m["per_class"]).T[["precision", "recall", "f1-score", "support"]].round(3)
    st.dataframe(pc)

st.subheader("Confidence threshold: coverage vs accuracy")
t = m["threshold"]
curve = pd.DataFrame(m["curve"])
fig = go.Figure()
fig.add_scatter(x=curve.threshold, y=curve.coverage, name="coverage (auto-routed share)", mode="lines+markers")
fig.add_scatter(x=curve.threshold, y=curve.accuracy, name="accuracy of auto-routed", mode="lines+markers")
fig.add_vline(x=t["value"], line_dash="dash", annotation_text=f"chosen {t['value']}")
fig.add_hline(y=t["target_accuracy"], line_dash="dot", line_color="grey", annotation_text="95% target")
fig.update_layout(yaxis_tickformat=".0%", xaxis_title="confidence threshold")
st.plotly_chart(fig)
rule = {"accuracy_target": "lowest threshold where auto-routed accuracy >= 95%",
        "max_acc_cov60": "no threshold reached 95%, so: highest auto-routed accuracy with coverage >= 60%", "default": "fallback default"}[t["rule"]]
st.info(f"**Default threshold {t['value']}** chosen by rule *{t['rule']}* ({rule}) -> auto-routed accuracy {t['accuracy']:.1%} at {t['coverage']:.1%} coverage.")
ui.export(curve, "threshold_curve")

hw = m["handwritten"]
st.subheader("Out-of-template check (hand-written tickets)")
st.write(f"n = **{hw['n']}**, category accuracy **{hw['accuracy']:.0%}**, ticket-type accuracy {hw['ticket_type_accuracy']:.0%}, mean confidence {hw['mean_confidence']:.2f}. "
         f"{'⚠ ' + hw['note'] if hw['note'] else ''}  Reported separately because synthetic text is template-generated and overstates real-world accuracy.")

fb = feedback_df()
st.subheader("Human-in-the-loop & feedback")
d = st.columns(3)
d[0].metric("Agent corrections recorded", len(fb))
d[1].metric("Used in training", int(fb.used_in_training.sum()) if len(fb) else 0)
d[2].metric("Needs Review queue", int((df.routed_queue == "Needs Review").sum()))
low = df[df.routed_queue == "Needs Review"].sort_values("confidence")[["ticket_id", "created_at", "subject", "category", "confidence", "true_category", "priority"]]
st.markdown("**Low-confidence tickets (sent to Needs Review)**")
st.dataframe(low.head(200), hide_index=True)
ui.export(low, "low_confidence_tickets")
