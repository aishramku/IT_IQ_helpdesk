"""Shared dashboard helpers: path setup, page chrome, cached data, CSV export."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(1, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.analytics import incidents_df, kpi_frame, tickets_df  # noqa: E402
from app.config import ARTIFACTS  # noqa: E402

# categorical palette (colour-blind friendly), fixed per category so colours mean the same everywhere
CAT_COLORS = {"Hardware": "#4C78A8", "Network": "#F58518", "Access/Password": "#54A24B", "Software": "#B279A2",
              "Email": "#E45756", "Printer": "#72B7B2"}
PRIO_COLORS = {"P1": "#C0392B", "P2": "#E67E22", "P3": "#2E86C1", "P4": "#95A5A6"}


def setup(title: str, icon: str = "🎫") -> None:
    st.set_page_config(page_title=f"TriageIQ - {title}", page_icon=icon, layout="wide")
    st.markdown("<style>div[data-testid='stMetricValue']{font-size:1.7rem}</style>", unsafe_allow_html=True)
    st.title(f"{icon} {title}")


@st.cache_data(ttl=30, show_spinner="Loading tickets...")
def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    return tickets_df(), incidents_df()


def data() -> tuple[pd.DataFrame, pd.DataFrame]:
    df, inc = load()
    if df.empty or df.routed_queue.isna().all():
        st.warning("No processed tickets yet. Run: `python -m scripts.load_history` then `python -m scripts.process_backlog`.")
        st.stop()
    return df, inc


def kpi(df: pd.DataFrame, inc: pd.DataFrame) -> pd.DataFrame:
    return kpi_frame(df, inc)


@st.cache_data(ttl=30)
def metrics() -> dict:
    p = ARTIFACTS / "metrics.json"
    return json.loads(p.read_text()) if p.exists() else {}


@st.cache_data(ttl=300)
def test_ids() -> set:
    """Tickets held out from training (ml/artifacts/test_set.csv): the only honest basis for routing accuracy."""
    p = ARTIFACTS / "test_set.csv"
    return set(pd.read_csv(p).ticket_id) if p.exists() else set()


def heldout(df: pd.DataFrame) -> pd.DataFrame:
    ids = test_ids()
    return df[df.ticket_id.isin(ids)] if ids else df


def export(df: pd.DataFrame, name: str, label: str | None = None) -> None:
    """CSV download button (load the file straight into Power BI)."""
    st.download_button(f"⬇ Export {label or name} to CSV", df.to_csv(index=False).encode("utf-8"), f"triageiq_{name}.csv", "text/csv", key=f"dl-{name}")
