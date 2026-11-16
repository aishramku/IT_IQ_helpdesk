"""Major-incident detection (runs AFTER duplicate merging).

Sliding window: when a new ticket arrives, look back `incident_window_minutes`; if the
tickets in that window that are similar to it (same predicted category, cosine >= threshold)
come from >= `incident_min_distinct_requesters` DISTINCT requesters, open a P1 major
incident and link the children. Counting distinct requesters (not tickets) means one
person spamming the helpdesk can never fake an incident.

SLA/MTTR is tracked on the parent Incident record; children are linked and re-prioritised
(audited) but excluded from SLA KPIs so P1 breach rates are not inflated.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.audit import log_decision
from app.config import get_settings
from app.intelligence.similarity import sims_to
from app.models import Incident, Ticket

ATTACH_GRACE = timedelta(minutes=60)  # late reporters still join an open incident


def _reprioritise(s: Session, t: Ticket, inc: Incident, n_req: int, ts: datetime | None) -> None:
    old = t.priority
    t.incident_id = inc.incident_id
    if old != "P1":
        t.priority = "P1"
    log_decision(s, t.ticket_id, "reprioritisation", f"priority {old} -> P1",
                 f"linked to major incident {inc.incident_id}: {n_req} distinct requesters reporting the same {inc.category} issue "
                 f"within {get_settings().incident_window_minutes} min", ts=ts,
                 details={"old": old, "new": "P1", "incident": inc.incident_id})


def _refresh(s: Session, inc: Incident) -> None:
    kids = s.query(Ticket).filter(Ticket.incident_id == inc.incident_id).all()
    inc.ticket_count = len(kids)
    inc.distinct_requesters = len({k.requester_email for k in kids})
    inc.window_start = min(k.created_at for k in kids)
    inc.window_end = max(k.created_at for k in kids)


def finalize_incidents(s: Session) -> None:
    """Close incidents whose children are all resolved (resolution time = last child resolved).

    Run after a replay/batch, or periodically live. Kept separate from linking so that
    already-resolved history cannot close an incident while it is still being detected.
    """
    for inc in s.query(Incident).all():
        kids = s.query(Ticket).filter(Ticket.incident_id == inc.incident_id).all()
        if kids and all(k.resolved_at for k in kids):
            inc.resolved_at, inc.status = max(k.resolved_at for k in kids), "Resolved"
        else:
            inc.resolved_at, inc.status = None, "Open"


def check_incident(s: Session, t: Ticket, ts: datetime | None = None) -> Incident | None:
    cfg = get_settings()
    if t.security_flag or t.duplicate_of or not t.clean_text or not t.category:
        return None

    # 1) join an open incident of the same category if this ticket looks like it
    open_inc = (s.query(Incident).filter(Incident.status == "Open", Incident.category == t.category,
                                         Incident.window_end >= t.created_at - ATTACH_GRACE).order_by(Incident.detected_at.desc()).first())
    if open_inc:
        # single-linkage: similar to ANY existing child (incident reports use varied wording)
        kids = s.query(Ticket.clean_text).filter(Ticket.incident_id == open_inc.incident_id).all()
        # (looser bar than opening an incident: same category + time + an already-declared incident is strong context)
        if sims_to(t.clean_text, [k[0] for k in kids]).max() >= cfg.incident_similarity * 0.7:
            _reprioritise(s, t, open_inc, open_inc.distinct_requesters, ts)
            s.flush()
            _refresh(s, open_inc)
            return open_inc

    # 2) look back over the sliding window for a new cluster
    cands = (s.query(Ticket).filter(Ticket.created_at >= t.created_at - timedelta(minutes=cfg.incident_window_minutes),
                                    Ticket.created_at <= t.created_at, Ticket.category == t.category,
                                    Ticket.incident_id.is_(None), Ticket.duplicate_of.is_(None),
                                    Ticket.security_flag.is_(None), Ticket.clean_text.isnot(None)).all())
    if len({c.requester_email for c in cands}) < cfg.incident_min_distinct_requesters:
        return None
    sims = sims_to(t.clean_text, [c.clean_text for c in cands])
    cluster = [c for c, sm in zip(cands, sims) if sm >= cfg.incident_similarity]
    n_req = len({c.requester_email for c in cluster})
    if n_req < cfg.incident_min_distinct_requesters:
        return None
    # retroactive single-linkage expansion: earlier reports worded differently still belong to the incident
    rest = [c for c in cands if c not in cluster]
    if rest:
        ctexts = [c.clean_text for c in cluster]
        cluster += [c for c in rest if sims_to(c.clean_text, ctexts).max() >= cfg.incident_similarity * 0.7]
        n_req = len({c.requester_email for c in cluster})

    cluster.sort(key=lambda c: c.created_at)
    seed = cluster[0]
    n = s.query(Incident).count() + 1
    inc = Incident(incident_id=f"INC-{n:04d}", title=f"Major incident: {t.category} - {seed.subject[:80]}", category=t.category,
                   priority="P1", status="Open", detected_at=t.created_at, window_start=seed.created_at, window_end=t.created_at,
                   seed_ticket_id=seed.ticket_id, ticket_count=len(cluster), distinct_requesters=n_req,
                   summary=f"{n_req} distinct requesters reported a similar {t.category} problem within "
                           f"{cfg.incident_window_minutes} minutes (auto-detected).")
    s.add(inc)
    s.flush()
    for c in cluster:
        _reprioritise(s, c, inc, n_req, ts)
    log_decision(s, t.ticket_id, "major_incident", f"created {inc.incident_id} (P1)",
                 f"{n_req} distinct requesters, {len(cluster)} similar tickets in {cfg.incident_window_minutes} min "
                 f"(threshold {cfg.incident_min_distinct_requesters})", ts=ts, details={"incident": inc.incident_id, "children": len(cluster)})
    s.flush()
    _refresh(s, inc)
    return inc
