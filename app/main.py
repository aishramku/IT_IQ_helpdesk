"""FastAPI service: ticket ingestion, email webhook, queues, KB, feedback.

    uvicorn app.main:app --reload
"""
from __future__ import annotations

import hmac
import os
import re
from datetime import datetime
from email.utils import parseaddr

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit import log_decision
from app.db import engine, get_session
from app.models import AuditLog, Base, Feedback, Ticket
from app.pipeline import kb as kb_mod
from app.pipeline.orchestrator import process_ticket, run_intelligence
from app.read_api import router as read_router
from app.schemas import EmailWebhookIn, FeedbackIn, TicketIn, TicketOut
from app.config import get_settings

app = FastAPI(title="TriageIQ", version="1.0", description="Automated IT helpdesk ticket triage")
Base.metadata.create_all(engine)
app.add_middleware(  # Vite dev server origins; override with CORS_ORIGINS="https://a,https://b"
    CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
    allow_methods=["*"], allow_headers=["*"])
app.include_router(read_router)


def _to_out(t: Ticket, reason: str | None = None) -> TicketOut:
    url = f"{get_settings().api_url}/kb/{t.kb_article_id}" if t.kb_article_id else None
    return TicketOut(ticket_id=t.ticket_id, status=t.status, category=t.category, ticket_type=t.ticket_type, confidence=t.confidence,
                     priority=t.priority, routed_queue=t.routed_queue, kb_article_id=t.kb_article_id, kb_url=url, action_tier=t.action_tier,
                     action_status=t.action_status, security_flag=t.security_flag, incident_id=t.incident_id, duplicate_of=t.duplicate_of,
                     reason=reason)


def _ingest(s: Session, *, email: str, subject: str, body: str, dept: str | None, loc: str | None, source: str,
            created: datetime | None = None) -> Ticket:
    t = Ticket(ticket_id=f"TMP-{os.urandom(6).hex()}", source=source, created_at=created or datetime.utcnow(), requester_email=email.lower(),
               department=dept, location=loc, subject=subject, raw_body=body, status="New")
    s.add(t)
    s.flush()
    t.ticket_id = f"TCK-{t.id:06d}"  # id from the DB sequence: collision-free under concurrent requests
    log_decision(s, t.ticket_id, "ingest", f"received via {source}", f"requester={email}", ts=t.created_at)
    process_ticket(s, t, live=True)
    s.flush()
    run_intelligence(s, t)
    return t


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/tickets", response_model=TicketOut, status_code=201)
def create_ticket(p: TicketIn, s: Session = Depends(get_session)) -> TicketOut:
    t = _ingest(s, email=p.requester_email, subject=p.subject, body=p.body, dept=p.department, loc=p.location, source="api")
    return _to_out(t)


def _html_to_text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", html))).strip()


@app.post("/webhook/email", response_model=TicketOut, status_code=201)
def email_webhook(p: EmailWebhookIn, s: Session = Depends(get_session), x_webhook_token: str | None = Header(default=None)) -> TicketOut:
    expected = os.getenv("WEBHOOK_TOKEN", "")
    if expected and not hmac.compare_digest(expected, x_webhook_token or ""):  # optional shared secret
        raise HTTPException(401, "invalid webhook token")
    _, addr = parseaddr(p.sender)
    if "@" not in addr:
        raise HTTPException(422, "sender has no valid address")
    body = p.text or (_html_to_text(p.html) if p.html else "")
    if not body.strip():
        raise HTTPException(422, "empty email body")
    if p.message_id:  # idempotency: providers retry webhooks
        prev = s.query(AuditLog).filter(AuditLog.step == "ingest", AuditLog.reason.like(f"%{p.message_id}%")).first()
        if prev:
            return _to_out(s.query(Ticket).filter(Ticket.ticket_id == prev.ticket_id).one(), "duplicate webhook delivery ignored")
    t = _ingest(s, email=addr, subject=p.subject or "(no subject)", body=body, dept=None, loc=None, source="email", created=p.received_at)
    if p.message_id:
        log_decision(s, t.ticket_id, "ingest", "email_message_id", f"message_id={p.message_id}")
    return _to_out(t)


@app.get("/queues")
def queues(s: Session = Depends(get_session)) -> dict:
    return {q or "unprocessed": n for q, n in s.query(Ticket.routed_queue, func.count()).group_by(Ticket.routed_queue).all()}


@app.get("/kb/{kb_id}", response_class=PlainTextResponse)
def kb_article(kb_id: str) -> str:
    a = kb_mod.get_article(kb_id)
    if not a:
        raise HTTPException(404, "article not found")
    return a.body


@app.post("/feedback", status_code=201)
def feedback(p: FeedbackIn, s: Session = Depends(get_session)) -> dict:
    t = s.query(Ticket).filter(Ticket.ticket_id == p.ticket_id).first()
    if not t:
        raise HTTPException(404, "ticket not found")
    s.add(Feedback(ticket_id=p.ticket_id, agent=p.agent, corrected_category=p.corrected_category,
                   corrected_ticket_type=p.corrected_ticket_type, corrected_priority=p.corrected_priority, comment=p.comment))
    log_decision(s, p.ticket_id, "feedback", "agent_correction", f"{p.corrected_category or ''} {p.corrected_priority or ''} {p.comment or ''}".strip(),
                 actor=f"agent:{p.agent or 'unknown'}")
    s.flush()
    return {"status": "recorded", "feedback_total": s.query(Feedback).count()}
