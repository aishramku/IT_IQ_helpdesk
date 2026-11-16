"""Read-side REST API for the web frontend (thin: reuses analytics / intelligence / security modules)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.analytics import audit_df, feedback_df, incidents_df, kpi_frame, overview, tickets_df
from app.audit import log_decision
from app.config import ARTIFACTS, get_settings
from app.constants import QUEUE_NEEDS_REVIEW, SLA_HOURS, TEAMS
from app.db import get_session
from app.intelligence.impact import before_after
from app.intelligence.recurring import analyze
from app.models import AuditLog, Entity, Feedback, Incident, RoutingLog, Ticket
from app.pipeline import kb as kb_mod
from app.security.action_policy import plan_actions
from app.security.injection import detect_injection
from app.security.sender_domain import classify_sender
from app.security.social_engineering import detect_social_engineering

router = APIRouter()
PRIO_ORDER = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


# ----------------------------------------------------------------------------- models
class TicketRow(BaseModel):
    ticket_id: str
    subject: str
    created_at: datetime
    requester_email: str
    department: str | None
    location: str | None
    category: str | None
    ticket_type: str | None
    confidence: float | None
    priority: str | None
    routed_queue: str | None
    status: str
    kb_article_id: str | None
    action_tier: str | None
    action_status: str | None
    security_flag: str | None
    incident_id: str | None
    duplicate_of: str | None
    resolved_at: datetime | None
    sla_hours: int | None
    sla_due_at: datetime | None
    sla_breached: bool


class TicketPage(BaseModel):
    items: list[TicketRow]
    total: int
    page: int
    page_size: int
    queue_counts: dict[str, int]


class EntityOut(BaseModel):
    type: str
    value: str


class AuditEntry(BaseModel):
    ts: datetime
    ticket_id: str | None = None
    actor: str
    step: str
    decision: str
    reason: str | None


class RoutingEntry(BaseModel):
    ts: datetime
    from_queue: str | None
    to_queue: str | None
    confidence: float | None
    reason: str | None


class ClassificationOut(BaseModel):
    category: str | None
    ticket_type: str | None
    confidence: float | None
    type_confidence: float | None
    method: str | None
    model_version: str | None
    threshold: float


class PriorityDetail(BaseModel):
    priority: str | None
    initial_priority: str | None
    impact: int | None
    urgency: int | None
    reasons: list[str]


class SecurityDetail(BaseModel):
    flag: str | None
    score: float | None
    injection_score: float
    injection_signals: list[str]
    social_score: float
    social_signals: list[str]
    sender_domain: str | None
    sender_class: str


class KbOut(BaseModel):
    id: str
    title: str
    score: float | None
    url: str


class ActionOut(BaseModel):
    tier: str | None
    status: str | None
    safe_actions: list[str]
    approval_actions: list[str]
    note: str


class FeedbackOut(BaseModel):
    ts: datetime
    agent: str | None
    corrected_category: str | None
    corrected_ticket_type: str | None
    corrected_priority: str | None
    comment: str | None


class TicketDetail(BaseModel):
    ticket: TicketRow
    clean_text: str | None
    source: str
    classification: ClassificationOut
    entities: list[EntityOut]
    priority_detail: PriorityDetail
    routing_reason: str | None
    kb: KbOut | None
    action: ActionOut
    security: SecurityDetail
    audit_log: list[AuditEntry]
    routing_log: list[RoutingEntry]
    feedback: list[FeedbackOut]


class RawBody(BaseModel):
    ticket_id: str
    raw_body: str
    warning: str


class IncidentRow(BaseModel):
    incident_id: str
    title: str
    category: str | None
    priority: str
    status: str
    detected_at: datetime
    window_start: datetime | None
    window_end: datetime | None
    resolved_at: datetime | None
    ticket_count: int
    distinct_requesters: int
    locations: dict[str, int]
    summary: str | None


class TimelinePoint(BaseModel):
    minute: int  # minutes since the first linked ticket
    ts: datetime
    new_tickets: int
    cumulative: int


class IncidentDetail(BaseModel):
    incident: IncidentRow
    children: list[TicketRow]
    timeline: list[TimelinePoint]
    detection_lag_minutes: float | None
    resolution_hours: float | None
    reprioritisations: list[AuditEntry]


class ActionIn(BaseModel):
    action: Literal["approve_action", "mark_resolved"]
    agent: str | None = None


# ----------------------------------------------------------------------------- helpers
def _row(t: Ticket) -> TicketRow:
    sla = SLA_HOURS.get(t.priority or "")
    due = t.created_at + timedelta(hours=sla) if sla else None
    breached = bool(due and ((t.resolved_at and t.resolved_at > due) or (not t.resolved_at and t.status != "Merged" and datetime.utcnow() > due)))
    return TicketRow(
        ticket_id=t.ticket_id, subject=t.subject, created_at=t.created_at, requester_email=t.requester_email, department=t.department,
        location=t.location, category=t.category, ticket_type=t.ticket_type, confidence=t.confidence, priority=t.priority,
        routed_queue=t.routed_queue, status=t.status, kb_article_id=t.kb_article_id, action_tier=t.action_tier, action_status=t.action_status,
        security_flag=t.security_flag, incident_id=t.incident_id, duplicate_of=t.duplicate_of, resolved_at=t.resolved_at, sla_hours=sla,
        sla_due_at=due, sla_breached=breached)


def _audit(a: AuditLog) -> AuditEntry:
    return AuditEntry(ts=a.ts, ticket_id=a.ticket_id, actor=a.actor, step=a.step, decision=a.decision, reason=a.reason)


def _f(v) -> float | None:
    return None if v is None or pd.isna(v) else float(v)


def _range(df: pd.DataFrame, start: date | None, end: date | None) -> pd.DataFrame:
    if start:
        df = df[df.created_at >= pd.Timestamp(start)]
    if end:
        df = df[df.created_at < pd.Timestamp(end) + pd.Timedelta(days=1)]
    return df


def _filtered_query(s: Session, category, priority, ticket_type, status, search):
    q = s.query(Ticket)
    if category:
        q = q.filter(Ticket.category == category)
    if priority:
        q = q.filter(Ticket.priority == priority)
    if ticket_type:
        q = q.filter(Ticket.ticket_type == ticket_type)
    if status:
        q = q.filter(Ticket.status == status)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(or_(Ticket.subject.ilike(like), Ticket.ticket_id.ilike(like), Ticket.requester_email.ilike(like)))
    return q


# ----------------------------------------------------------------------------- tickets
@router.get("/tickets", response_model=TicketPage, tags=["tickets"])
def list_tickets(queue: str | None = None, status: str | None = None, category: str | None = None, priority: str | None = None,
                 ticket_type: str | None = None, search: str | None = None,
                 sort: Literal["created_at", "priority", "confidence"] = "created_at", order: Literal["asc", "desc"] = "desc",
                 page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), s: Session = Depends(get_session)) -> TicketPage:
    base = _filtered_query(s, category, priority, ticket_type, status, search)
    counts = {(q_ or "unprocessed"): n for q_, n in base.with_entities(Ticket.routed_queue, func.count()).group_by(Ticket.routed_queue).all()}
    q = base.filter(Ticket.routed_queue == queue) if queue else base
    total = q.count()
    col = {"created_at": Ticket.created_at, "priority": Ticket.priority, "confidence": Ticket.confidence}[sort]
    q = q.order_by(col.asc() if order == "asc" else col.desc(), Ticket.id.desc())
    items = [_row(t) for t in q.offset((page - 1) * page_size).limit(page_size).all()]
    return TicketPage(items=items, total=total, page=page, page_size=page_size, queue_counts=counts)


@router.get("/tickets/{ticket_id}", response_model=TicketDetail, tags=["tickets"])
def ticket_detail(ticket_id: str, s: Session = Depends(get_session)) -> TicketDetail:
    t = s.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not t:
        raise HTTPException(404, "ticket not found")
    cfg = get_settings()
    cls = t.classifications[-1] if t.classifications else None
    audit = s.query(AuditLog).filter(AuditLog.ticket_id == ticket_id).order_by(AuditLog.ts, AuditLog.id).all()
    route = s.query(RoutingLog).filter(RoutingLog.ticket_pk == t.id).order_by(RoutingLog.id).all()
    ents = s.query(Entity).filter(Entity.ticket_pk == t.id).all()
    fbs = s.query(Feedback).filter(Feedback.ticket_id == ticket_id).order_by(Feedback.id).all()
    text = t.clean_text or ""
    inj = detect_injection(text)
    se = detect_social_engineering(text, t.requester_email, cfg.corporate_domain)
    prio_reason = next((a.reason for a in audit if a.step == "priority"), None)
    plan = plan_actions(text, t.category or "", t.ticket_type or "", t.kb_article_id is not None, t.security_flag) if t.category else None
    art = kb_mod.get_article(t.kb_article_id) if t.kb_article_id else None
    return TicketDetail(
        ticket=_row(t), clean_text=t.clean_text, source=t.source,
        classification=ClassificationOut(category=t.category, ticket_type=t.ticket_type, confidence=t.confidence,
                                         type_confidence=cls.type_confidence if cls else None, method=cls.method if cls else None,
                                         model_version=cls.model_version if cls else None, threshold=cfg.threshold),
        entities=[EntityOut(type=e.entity_type, value=e.value) for e in ents],
        priority_detail=PriorityDetail(priority=t.priority, initial_priority=t.initial_priority, impact=t.impact, urgency=t.urgency,
                                       reasons=(prio_reason or "").split("; ") if prio_reason else []),
        routing_reason=route[-1].reason if route else None,
        kb=KbOut(id=art.id, title=art.title, score=t.kb_score, url=f"{cfg.api_url}/kb/{art.id}") if art else None,
        action=ActionOut(tier=t.action_tier, status=t.action_status, safe_actions=plan.safe_actions if plan else [],
                         approval_actions=plan.approval_actions if plan else [], note=plan.note if plan else ""),
        security=SecurityDetail(flag=t.security_flag, score=t.security_score, injection_score=inj.score, injection_signals=inj.matches,
                                social_score=se.score, social_signals=se.signals, sender_domain=t.sender_domain, sender_class=se.sender_class),
        audit_log=[_audit(a) for a in audit],
        routing_log=[RoutingEntry(ts=r.ts, from_queue=r.from_queue, to_queue=r.to_queue, confidence=r.confidence, reason=r.reason) for r in route],
        feedback=[FeedbackOut(ts=f.ts, agent=f.agent, corrected_category=f.corrected_category, corrected_ticket_type=f.corrected_ticket_type,
                              corrected_priority=f.corrected_priority, comment=f.comment) for f in fbs])


@router.get("/tickets/{ticket_id}/raw", response_model=RawBody, tags=["tickets"])
def ticket_raw(ticket_id: str, agent: str | None = None, s: Session = Depends(get_session)) -> RawBody:
    """RESTRICTED: original body (may contain PII). Every access is written to the audit log."""
    t = s.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not t:
        raise HTTPException(404, "ticket not found")
    log_decision(s, ticket_id, "restricted_access", "raw_body_viewed", "original (unredacted) body opened", actor=f"agent:{agent or 'unknown'}")
    return RawBody(ticket_id=ticket_id, raw_body=t.raw_body, warning="Restricted: may contain personal data. This access has been logged.")


@router.post("/tickets/{ticket_id}/actions", response_model=TicketRow, tags=["tickets"])
def ticket_action(ticket_id: str, p: ActionIn, s: Session = Depends(get_session)) -> TicketRow:
    """Records an agent decision. It NEVER executes anything: approving only marks the action as approved for a human/system of record."""
    t = s.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not t:
        raise HTTPException(404, "ticket not found")
    who = f"agent:{p.agent or 'unknown'}"
    if p.action == "approve_action":
        if t.action_tier != "REQUIRES_APPROVAL" or t.security_flag:
            raise HTTPException(409, "nothing to approve: no approval-gated action, or ticket is security-flagged")
        t.action_status = "approved_pending_execution"
        log_decision(s, ticket_id, "agent_action", "action_approved", "approval recorded; execution stays with the identity/access system (simulated)", actor=who)
    else:
        t.status, t.resolved_at = "Resolved", datetime.utcnow()
        log_decision(s, ticket_id, "agent_action", "marked_resolved", "agent resolved the ticket", actor=who)
    s.flush()
    return _row(t)


# ----------------------------------------------------------------------------- incidents
def _incident_row(s: Session, i: Incident) -> IncidentRow:
    locs = dict(s.query(Ticket.location, func.count()).filter(Ticket.incident_id == i.incident_id).group_by(Ticket.location).all())
    return IncidentRow(incident_id=i.incident_id, title=i.title, category=i.category, priority=i.priority, status=i.status, detected_at=i.detected_at,
                       window_start=i.window_start, window_end=i.window_end, resolved_at=i.resolved_at, ticket_count=i.ticket_count,
                       distinct_requesters=i.distinct_requesters, locations={k or "Unknown": v for k, v in locs.items()}, summary=i.summary)


@router.get("/incidents", response_model=list[IncidentRow], tags=["incidents"])
def list_incidents(s: Session = Depends(get_session)) -> list[IncidentRow]:
    return [_incident_row(s, i) for i in s.query(Incident).order_by(Incident.detected_at.desc()).all()]


@router.get("/incidents/{incident_id}", response_model=IncidentDetail, tags=["incidents"])
def incident_detail(incident_id: str, s: Session = Depends(get_session)) -> IncidentDetail:
    i = s.query(Incident).filter(Incident.incident_id == incident_id).first()
    if not i:
        raise HTTPException(404, "incident not found")
    kids = s.query(Ticket).filter(Ticket.incident_id == incident_id).order_by(Ticket.created_at).all()
    t0 = kids[0].created_at if kids else i.detected_at
    buckets: dict[int, int] = {}
    for k in kids:
        m = int((k.created_at - t0).total_seconds() // 60)
        buckets[m] = buckets.get(m, 0) + 1
    last = max(buckets) if buckets else 0
    cum, timeline = 0, []
    for m in range(0, last + 1):
        cum += buckets.get(m, 0)
        timeline.append(TimelinePoint(minute=m, ts=t0 + timedelta(minutes=m), new_tickets=buckets.get(m, 0), cumulative=cum))
    ids = [k.ticket_id for k in kids]
    rep = (s.query(AuditLog).filter(AuditLog.step == "reprioritisation", AuditLog.ticket_id.in_(ids)).order_by(AuditLog.ts).all() if ids else [])
    return IncidentDetail(
        incident=_incident_row(s, i), children=[_row(k) for k in kids], timeline=timeline,
        detection_lag_minutes=(i.detected_at - t0).total_seconds() / 60 if kids else None,
        resolution_hours=(i.resolved_at - t0).total_seconds() / 3600 if i.resolved_at and kids else None,
        reprioritisations=[_audit(a) for a in rep])


# ----------------------------------------------------------------------------- analytics
def _frames(start: date | None, end: date | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    df, inc = tickets_df(), incidents_df()
    df = _range(df, start, end)
    if len(inc):
        inc = inc[inc.incident_id.isin(df.incident_id.dropna().unique())] if (start or end) else inc
    return df, inc


def _heldout(df: pd.DataFrame) -> pd.DataFrame:
    p = ARTIFACTS / "test_set.csv"
    if not p.exists():
        return df
    return df[df.ticket_id.isin(set(pd.read_csv(p).ticket_id))]


def _metrics() -> dict:
    p = ARTIFACTS / "metrics.json"
    return json.loads(p.read_text()) if p.exists() else {}


@router.get("/analytics/overview", tags=["analytics"])
def analytics_overview(start: date | None = None, end: date | None = None) -> dict:
    df, inc = _frames(start, end)
    o = overview(df, inc) if len(df) else {k: 0 for k in ("total", "open", "resolved", "merged", "auto_routed_pct", "needs_review_pct", "security_review",
                                                          "deflection_rate", "kb_suggested_pct", "incidents", "incident_share", "sr_share")}
    k = kpi_frame(df, inc) if len(df) else pd.DataFrame(columns=["resolution_hours", "breached", "reassignment_count"])
    o.update(mttr_hours=_f(k.resolution_hours.mean()) if len(k) else None, sla_breach_rate=_f(k.breached.mean()) if len(k) else None,
             fcr=_f((k.reassignment_count == 0).mean()) if len(k) else None,
             type_counts=df.ticket_type.value_counts().to_dict() if len(df) else {},
             queue_counts=df.routed_queue.value_counts().to_dict() if len(df) else {},
             date_min=df.created_at.min() if len(df) else None, date_max=df.created_at.max() if len(df) else None)
    return _jsonable(o)


def _jsonable(o):
    """Make pandas/numpy values JSON-safe (NaN/NaT -> null, numpy scalars -> python, timestamps -> ISO)."""
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if o is pd.NaT:
        return None
    if isinstance(o, (pd.Timestamp, datetime, date)):
        return o.isoformat()
    if isinstance(o, np.generic):
        o = o.item()
    if isinstance(o, float) and o != o:
        return None
    return o


@router.get("/analytics/kpis", tags=["analytics"])
def analytics_kpis(start: date | None = None, end: date | None = None) -> dict:
    df, inc = _frames(start, end)
    k = kpi_frame(df, inc) if len(df) else pd.DataFrame()
    if k.empty:
        return {"mttr_by_category": [], "sla_by_priority": [], "fcr_by_category": [], "sla_targets": SLA_HOURS, "tickets_in_scope": 0}
    mttr = k.groupby("category").resolution_hours.agg(mean="mean", median="median", tickets="size").round(2).reset_index()
    sla = k.groupby("kpi_priority").agg(breach_rate=("breached", "mean"), tickets=("breached", "size")).reset_index().sort_values("kpi_priority")
    fcr = k.groupby("category").apply(lambda g: (g.reassignment_count == 0).mean(), include_groups=False).reset_index(name="fcr")
    return _jsonable({"mttr_by_category": mttr.to_dict("records"),
                      "sla_by_priority": [{"priority": r.kpi_priority, "breach_rate": r.breach_rate, "tickets": r.tickets, "sla_hours": SLA_HOURS[r.kpi_priority]}
                                          for r in sla.itertuples()],
                      "fcr_by_category": fcr.to_dict("records"), "sla_targets": SLA_HOURS, "tickets_in_scope": len(k),
                      "note": "major-incident children are excluded; the parent incident is counted once as P1"})


@router.get("/analytics/trends", tags=["analytics"])
def analytics_trends(start: date | None = None, end: date | None = None) -> dict:
    df, _ = _frames(start, end)
    df = df[~df.is_malicious.astype(bool)]
    if df.empty:
        return {"volume_by_day": [], "heatmap": [], "category_weekly": [], "type_weekly": [], "location_category": []}
    day = df.groupby([df.date, "ticket_type"]).size().unstack(fill_value=0)
    vol = [{"date": d.date().isoformat(), "incident": int(r.get("Incident", 0)), "service_request": int(r.get("Service Request", 0)),
            "total": int(r.sum())} for d, r in day.iterrows()]
    heat = [{"dow": int(a), "hour": int(b), "count": int(c)} for (a, b), c in df.groupby(["dow", "hour"]).size().items()]
    wk = df.assign(week=df.created_at.dt.to_period("W").dt.start_time.dt.date.astype(str))
    cat = [{"week": a, "category": b, "tickets": int(c)} for (a, b), c in wk.groupby(["week", "category"]).size().items()]
    typ = [{"week": a, "ticket_type": b, "tickets": int(c)} for (a, b), c in wk.groupby(["week", "ticket_type"]).size().items()]
    loc = [{"location": a, "category": b, "tickets": int(c)} for (a, b), c in df.groupby(["location", "category"]).size().items()]
    return {"volume_by_day": vol, "heatmap": heat, "category_weekly": cat, "type_weekly": typ, "location_category": loc}


@router.get("/analytics/insights", tags=["analytics"])
def analytics_insights() -> dict:
    df, inc = tickets_df(), incidents_df()
    if df.empty or df.routed_queue.isna().all():
        return {"insights": [], "before_after": {"heldout": None, "all": None}}
    return _jsonable({"insights": [i.__dict__ for i in analyze(df, inc)],
                      "before_after": {"heldout": before_after(_heldout(df)), "all": before_after(df)}})


@router.get("/analytics/impact", tags=["analytics"])
def analytics_impact() -> dict:
    """Measured rates the calculator multiplies by the user's assumptions (held-out tickets for routing rates)."""
    df, inc = tickets_df(), incidents_df()
    if df.empty or df.routed_queue.isna().all():
        return {"available": False}
    ho = _heldout(df)
    oh, ba, oa = overview(ho, inc), before_after(ho), overview(df, inc)
    days = max((df.created_at.max() - df.created_at.min()).days, 1)
    return _jsonable({
        "available": True, "monthly_volume": int(len(df) / days * 30), "heldout_tickets": len(ho), "auto_routed_pct": oh["auto_routed_pct"],
        "needs_review_pct": oh["needs_review_pct"], "reassignments_saved_per_ticket": ba["reassignments_saved"] / max(ba["tickets"], 1),
        "baseline_misroute_rate": ba["baseline_misroute_rate"], "pipeline_misroute_rate_of_auto": ba["pipeline_misroute_rate_of_auto"],
        "duplicate_rate": oa["merged"] / max(oa["total"], 1),
        "incident_children_rate": float((inc.ticket_count.sum() - len(inc)) / max(oa["total"], 1)) if len(inc) else 0.0,
        "defaults": {"handling_minutes": 20, "hourly_cost_inr": 450, "triage_share": 0.25, "reassign_minutes": 20, "review_minutes": 3, "kb_uplift": 0.03}})


@router.get("/analytics/model", tags=["analytics"])
def analytics_model(s: Session = Depends(get_session)) -> dict:
    m = _metrics()
    fb = feedback_df()
    last = s.query(AuditLog).filter(AuditLog.step == "retrain").order_by(AuditLog.ts.desc()).first()
    low = (s.query(Ticket).filter(Ticket.routed_queue == QUEUE_NEEDS_REVIEW).order_by(Ticket.confidence.asc()).limit(25).all())
    return _jsonable({"available": bool(m), "metrics": m, "feedback_count": len(fb),
                      "feedback_used": int(fb.used_in_training.sum()) if len(fb) else 0,
                      "last_retrain": {"ts": last.ts, "decision": last.decision, "reason": last.reason} if last else None,
                      "model_trained_at": (m or {}).get("generated_at"), "low_confidence": [_row(t).model_dump(mode="json") for t in low],
                      "needs_review_total": s.query(Ticket).filter(Ticket.routed_queue == QUEUE_NEEDS_REVIEW).count()})


@router.get("/analytics/security", tags=["analytics"])
def analytics_security(s: Session = Depends(get_session)) -> dict:
    cfg = get_settings()
    flagged = s.query(Ticket).filter(Ticket.security_flag.isnot(None)).order_by(Ticket.created_at.desc()).all()
    out = []
    for t in flagged:
        text = t.clean_text or ""
        inj, se = detect_injection(text), detect_social_engineering(text, t.requester_email, cfg.corporate_domain)
        out.append({"ticket": _row(t).model_dump(mode="json"), "flag": t.security_flag, "score": t.security_score,
                    "signals": inj.matches if t.security_flag == "prompt_injection" else se.signals, "sender_class": se.sender_class,
                    "sender_domain": t.sender_domain, "excerpt": text[:220]})
    by = {}
    for r in out:
        by[r["flag"]] = by.get(r["flag"], 0) + 1
    sc = {}
    for r in out:
        sc[r["sender_class"]] = sc.get(r["sender_class"], 0) + 1
    return _jsonable({"flagged": out, "counts": by, "sender_classes": sc, "metrics": _metrics().get("security"),
                      "auto_executed_actions": 0,
                      "action_status_counts": dict(s.query(Ticket.action_status, func.count()).group_by(Ticket.action_status).all())})
