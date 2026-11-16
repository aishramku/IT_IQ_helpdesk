"""Before/after impact: human L1 routing (baseline in the generated history) vs the pipeline's routing.

Ground truth for "correct team" is the team that actually resolved the ticket (`assigned_team`).
Honest accounting:
  * baseline misroute  = initial_team != assigned_team (recorded in history)
  * pipeline misroute  = auto-assigned queue != assigned_team (Needs Review tickets are NOT counted
    as misroutes - a human decides - but are reported as manual touches)
  * label noise in the history means some "pipeline misroutes" are really mislabelled truth; we do not hide them.
"""
from __future__ import annotations

import pandas as pd

from app.constants import QUEUE_NEEDS_REVIEW, TEAMS


def before_after(df: pd.DataFrame) -> dict:
    d = df[~df.is_malicious.astype(bool) & df.duplicate_of.isna() & df.routed_queue.notna() & df.initial_team.notna()
           & df.assigned_team.notna()].copy()
    n = len(d)
    base_mis = d.initial_team != d.assigned_team
    auto = d.routed_queue.isin(TEAMS)
    pipe_mis = auto & (d.routed_queue != d.assigned_team)
    review = d.routed_queue == QUEUE_NEEDS_REVIEW

    per_mis = float(d.loc[base_mis, "reassignment_count"].mean()) if base_mis.any() else 0.0
    base_reassign = int(d.reassignment_count.sum())
    # reassignments the pipeline would still incur: its own misroutes x the baseline reassignments-per-misroute
    pipe_reassign = pipe_mis.sum() * per_mis + float(d.loc[~base_mis, "reassignment_count"].sum())
    return {
        "tickets": n, "baseline_misroutes": int(base_mis.sum()), "baseline_misroute_rate": float(base_mis.mean()),
        "pipeline_auto_routed": int(auto.sum()), "pipeline_misroutes": int(pipe_mis.sum()),
        "pipeline_misroute_rate_of_all": float(pipe_mis.sum() / n), "pipeline_misroute_rate_of_auto": float(pipe_mis.sum() / max(auto.sum(), 1)),
        "needs_review": int(review.sum()), "needs_review_pct": float(review.mean()),
        "misroutes_avoided": int(base_mis.sum() - pipe_mis.sum()),
        "baseline_reassignments": base_reassign, "pipeline_reassignments_est": float(pipe_reassign),
        "reassignments_saved": float(base_reassign - pipe_reassign), "avg_reassignments_per_misroute": per_mis,
    }
