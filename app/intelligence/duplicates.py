"""Duplicate detection (runs FIRST, before major-incident clustering).

Rule: same requester + text similarity >= threshold within 24h -> merge into the original.
Distinct requesters reporting the same fault are NOT duplicates - that is incident territory.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.audit import log_decision
from app.config import get_settings
from app.intelligence.similarity import sims_to
from app.models import Ticket

WINDOW = timedelta(hours=24)


def check_duplicate(s: Session, t: Ticket, ts: datetime | None = None, live: bool = True) -> Ticket | None:
    if not t.clean_text or t.security_flag:
        return None
    thr = get_settings().duplicate_similarity
    cands = (s.query(Ticket).filter(Ticket.requester_email == t.requester_email, Ticket.id != t.id,
                                    Ticket.created_at >= t.created_at - WINDOW, Ticket.created_at < t.created_at,
                                    Ticket.duplicate_of.is_(None), Ticket.clean_text.isnot(None))
             .order_by(Ticket.created_at).all())
    if not cands:
        return None
    sims = sims_to(t.clean_text, [c.clean_text for c in cands])
    i = int(sims.argmax())
    if sims[i] < thr:
        return None
    orig = cands[i]
    t.duplicate_of = orig.ticket_id
    t.status = "Merged"
    log_decision(s, t.ticket_id, "duplicate_detection", f"merged into {orig.ticket_id}",
                 f"same requester, similarity {sims[i]:.2f} >= {thr:.2f} within 24h", ts=ts,
                 details={"original": orig.ticket_id, "similarity": round(float(sims[i]), 3)})
    return orig
