"""Load the synthetic history CSV into the tickets table (raw intake + ground truth).

    python -m scripts.load_history [--csv data/raw/tickets.csv] [--reset]

Pipeline columns (category, priority, ...) stay NULL until scripts/process_backlog.py runs.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from app.config import ROOT
from app.db import session_scope
from app.models import Ticket
from scripts.init_db import init_db


def _none(v):
    return None if pd.isna(v) or v == "" else v


def load(csv: Path, reset: bool = False) -> int:
    init_db(reset)
    df = pd.read_csv(csv, parse_dates=["created_at", "resolved_at"])
    with session_scope() as s:
        if s.query(Ticket).count():
            print("tickets table not empty - use --reset to reload")
            return 0
        rows = []
        for r in df.to_dict("records"):
            rows.append(Ticket(
                ticket_id=r["ticket_id"], source="synthetic", created_at=r["created_at"].to_pydatetime(),
                requester_email=r["requester_email"], sender_domain=r["requester_email"].split("@")[-1].lower(),
                department=_none(r["department"]), location=_none(r["location"]), subject=r["subject"], raw_body=r["body"],
                status=r["status"], resolved_at=None if pd.isna(r["resolved_at"]) else r["resolved_at"].to_pydatetime(),
                resolution_notes=_none(r["resolution_notes"]), assigned_team=_none(r["assigned_team"]),
                initial_team=_none(r["initial_team"]), reassignment_count=int(r["reassignment_count"]),
                resolution_channel=_none(r["resolution_channel"]), true_category=r["true_category"],
                true_priority=r["true_priority"], true_ticket_type=r["true_ticket_type"], subtype=_none(r["subtype"]),
                scenario=_none(r["scenario"]), is_malicious=bool(r["is_malicious"]), attack_type=_none(r["attack_type"]),
                dup_of_true=_none(r["dup_of"]),
            ))
        s.add_all(rows)
    return len(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(ROOT / "data" / "raw" / "tickets.csv"))
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()
    print(f"loaded {load(Path(a.csv), a.reset)} tickets")
