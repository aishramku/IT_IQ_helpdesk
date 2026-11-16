"""Read-side data access shared by the dashboard, the insight engine and the API.

Returns pandas DataFrames straight from the database (works on SQLite or PostgreSQL).
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text

from app.constants import QUEUE_NEEDS_REVIEW, SLA_HOURS, TEAMS
from app.db import engine

TICKET_COLS = """ticket_id, created_at, requester_email, sender_domain, department, location, subject, category, ticket_type, confidence,
  priority, initial_priority, impact, urgency, routed_queue, kb_article_id, kb_score, action_tier, action_status, security_flag,
  security_score, incident_id, duplicate_of, status, resolved_at, assigned_team, initial_team, reassignment_count,
  resolution_channel, true_category, true_priority, true_ticket_type, subtype, scenario, is_malicious, attack_type, clean_text"""


def tickets_df() -> pd.DataFrame:
    df = pd.read_sql(text(f"SELECT {TICKET_COLS} FROM tickets"), engine, parse_dates=["created_at", "resolved_at"])
    df["created_at"], df["resolved_at"] = pd.to_datetime(df.created_at), pd.to_datetime(df.resolved_at)  # all-NULL columns arrive as str
    df["resolution_hours"] = (df.resolved_at - df.created_at).dt.total_seconds() / 3600
    df["dow"], df["hour"] = df.created_at.dt.dayofweek, df.created_at.dt.hour
    df["date"] = df.created_at.dt.normalize()
    return df


def incidents_df() -> pd.DataFrame:
    inc = pd.read_sql(text("SELECT * FROM incidents ORDER BY detected_at"), engine)
    for c in ("detected_at", "window_start", "window_end", "resolved_at"):
        inc[c] = pd.to_datetime(inc[c])
    return inc


def audit_df(limit: int = 5000) -> pd.DataFrame:
    return pd.read_sql(text(f"SELECT * FROM audit_log ORDER BY id DESC LIMIT {int(limit)}"), engine, parse_dates=["ts"])


def feedback_df() -> pd.DataFrame:
    return pd.read_sql(text("SELECT * FROM feedback ORDER BY id DESC"), engine)


def kpi_frame(df: pd.DataFrame, inc: pd.DataFrame) -> pd.DataFrame:
    """Tickets that count toward SLA / MTTR.

    Excludes merged duplicates and security-closed tickets, and EXCLUDES major-incident children:
    the parent incident is counted once (as a synthetic P1 row) so P1 breach rates are not inflated.
    """
    base = df[df.duplicate_of.isna() & df.security_flag.isna() & df.incident_id.isna() & df.resolved_at.notna()].copy()
    base["kpi_priority"] = base.priority
    parents = inc[inc.resolved_at.notna()].copy()
    if len(parents):
        p = pd.DataFrame({"ticket_id": parents.incident_id, "category": parents.category, "kpi_priority": "P1", "priority": "P1",
                          "created_at": parents.window_start, "resolved_at": parents.resolved_at,
                          "resolution_hours": (parents.resolved_at - parents.window_start).dt.total_seconds() / 3600,
                          "resolution_channel": "agent", "reassignment_count": 0, "is_incident_parent": True})
        base = pd.concat([base, p], ignore_index=True)
    base["sla_hours"] = pd.to_numeric(base.kpi_priority.map(SLA_HOURS), errors="coerce")  # numeric even when empty
    base["breached"] = base.resolution_hours > base.sla_hours
    return base


def overview(df: pd.DataFrame, inc: pd.DataFrame) -> dict:
    proc = df[df.routed_queue.notna()]
    real = proc[~proc.is_malicious.astype(bool)]
    n = len(df)
    return {
        "total": n, "open": int((~df.status.isin(["Resolved", "Merged"])).sum()), "resolved": int((df.status == "Resolved").sum()),
        "merged": int((df.status == "Merged").sum()),
        "auto_routed_pct": float(proc.routed_queue.isin(TEAMS).mean()) if len(proc) else 0.0,
        "needs_review_pct": float((proc.routed_queue == QUEUE_NEEDS_REVIEW).mean()) if len(proc) else 0.0,
        "security_review": int((proc.routed_queue == "Security Review").sum()),
        "deflection_rate": float((real.resolution_channel == "self_service_kb").mean()) if len(real) else 0.0,
        "kb_suggested_pct": float(real.kb_article_id.notna().mean()) if len(real) else 0.0,
        "incidents": len(inc), "incident_share": float((df.ticket_type == "Incident").mean()), "sr_share": float((df.ticket_type == "Service Request").mean()),
    }
