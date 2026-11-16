"""Run the full pipeline + intelligence over the loaded history, in time order.

    python -m scripts.process_backlog [--limit N]

Replays history as if tickets arrived live: process -> duplicates -> major incidents.
Timestamps in audit_log / routing_log use the ticket's own created_at so dashboards line up.
"""
from __future__ import annotations

import argparse
import time
from collections import Counter
from datetime import timedelta

from sqlalchemy import update

from app.db import session_scope
from app.intelligence.incidents import finalize_incidents
from app.models import AuditLog, Classification, Entity, Incident, RoutingLog, Ticket
from app.pipeline.orchestrator import process_ticket, run_intelligence

RESET_FIELDS = dict(category=None, ticket_type=None, confidence=None, priority=None, initial_priority=None, impact=None, urgency=None,
                    routed_queue=None, kb_article_id=None, kb_score=None, action_tier=None, action_status=None, security_flag=None,
                    security_score=None, incident_id=None, duplicate_of=None, processed_at=None, clean_text=None)


def reset(s) -> None:
    s.execute(update(Ticket).values(**RESET_FIELDS))
    for m in (AuditLog, RoutingLog, Entity, Classification, Incident):
        s.query(m).delete()
    # history 'Merged' status was set by a previous run; restore the lifecycle status
    s.execute(update(Ticket).where(Ticket.status == "Merged").values(status="Resolved"))


def main(limit: int | None = None) -> Counter:
    t0 = time.time()
    stats: Counter = Counter()
    with session_scope() as s:
        reset(s)
    with session_scope() as s:
        ids = [r[0] for r in s.query(Ticket.id).order_by(Ticket.created_at, Ticket.id).limit(limit).all()]
    for n in range(0, len(ids), 250):
        with session_scope() as s:
            for tid in ids[n:n + 250]:
                t = s.get(Ticket, tid)
                out = process_ticket(s, t, live=False, now=t.created_at + timedelta(seconds=2))
                s.flush()
                run_intelligence(s, t, ts=t.created_at + timedelta(seconds=3))
                stats[out.queue] += 1
                stats["flag:" + str(out.security_flag)] += 1
        print(f"  processed {min(n + 250, len(ids))}/{len(ids)}", flush=True)
    with session_scope() as s:
        finalize_incidents(s)
        stats["incidents"] = s.query(Incident).count()
        stats["merged_duplicates"] = s.query(Ticket).filter(Ticket.duplicate_of.isnot(None)).count()
    print(f"done in {time.time() - t0:.0f}s: {dict(stats)}")
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    main(ap.parse_args().limit)
