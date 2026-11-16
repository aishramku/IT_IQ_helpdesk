"""ORM schema: tickets, classifications, entities, routing_log, incidents, audit_log, feedback."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Ticket(Base):
    """One row per ticket.

    Column groups:
      * intake            - what the requester sent (raw_body is a RESTRICTED column)
      * processed         - output of the pipeline (clean_text is PII-redacted)
      * history / ground truth - only populated for the synthetic history; used for
        evaluation and the before/after impact analysis, never as pipeline input
    """
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(20), default="api")  # synthetic|api|email
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    requester_email: Mapped[str] = mapped_column(String(255), index=True)
    sender_domain: Mapped[str | None] = mapped_column(String(120))
    department: Mapped[str | None] = mapped_column(String(60))
    location: Mapped[str | None] = mapped_column(String(60), index=True)
    subject: Mapped[str] = mapped_column(String(300))
    raw_body: Mapped[str] = mapped_column(Text)  # RESTRICTED: may contain PII
    clean_text: Mapped[str | None] = mapped_column(Text)  # PII-redacted, signature-stripped

    # --- pipeline outputs ---
    category: Mapped[str | None] = mapped_column(String(30), index=True)
    ticket_type: Mapped[str | None] = mapped_column(String(20))
    confidence: Mapped[float | None] = mapped_column(Float)
    priority: Mapped[str | None] = mapped_column(String(3), index=True)
    initial_priority: Mapped[str | None] = mapped_column(String(3))  # before incident re-prioritisation
    impact: Mapped[int | None] = mapped_column(Integer)
    urgency: Mapped[int | None] = mapped_column(Integer)
    routed_queue: Mapped[str | None] = mapped_column(String(40), index=True)
    kb_article_id: Mapped[str | None] = mapped_column(String(20))
    kb_score: Mapped[float | None] = mapped_column(Float)
    action_tier: Mapped[str | None] = mapped_column(String(20))  # SAFE | REQUIRES_APPROVAL
    action_status: Mapped[str | None] = mapped_column(String(30))  # e.g. verification_required
    security_flag: Mapped[str | None] = mapped_column(String(30), index=True)  # social_engineering|prompt_injection
    security_score: Mapped[float | None] = mapped_column(Float)
    incident_id: Mapped[str | None] = mapped_column(ForeignKey("incidents.incident_id"), index=True)
    duplicate_of: Mapped[str | None] = mapped_column(String(32), index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)

    # --- lifecycle / history ---
    status: Mapped[str] = mapped_column(String(25), default="New", index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    assigned_team: Mapped[str | None] = mapped_column(String(40))  # team that actually resolved it
    initial_team: Mapped[str | None] = mapped_column(String(40))  # baseline human L1 routing
    reassignment_count: Mapped[int] = mapped_column(Integer, default=0)
    resolution_channel: Mapped[str | None] = mapped_column(String(20))  # agent|self_service_kb|auto_ack

    # --- ground truth (synthetic history / evaluation only) ---
    true_category: Mapped[str | None] = mapped_column(String(30))
    true_priority: Mapped[str | None] = mapped_column(String(3))
    true_ticket_type: Mapped[str | None] = mapped_column(String(20))
    subtype: Mapped[str | None] = mapped_column(String(40))
    scenario: Mapped[str | None] = mapped_column(String(30))
    is_malicious: Mapped[bool] = mapped_column(Boolean, default=False)
    attack_type: Mapped[str | None] = mapped_column(String(30))
    dup_of_true: Mapped[str | None] = mapped_column(String(32))

    classifications: Mapped[list["Classification"]] = relationship(back_populates="ticket")
    entities: Mapped[list["Entity"]] = relationship(back_populates="ticket")

    __table_args__ = (Index("ix_tickets_req_created", "requester_email", "created_at"),)


class Classification(Base):
    __tablename__ = "classifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_pk: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    category: Mapped[str] = mapped_column(String(30))
    ticket_type: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float] = mapped_column(Float)
    type_confidence: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(20))  # sklearn | llm | llm_fallback
    model_version: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ticket: Mapped[Ticket] = relationship(back_populates="classifications")


class Entity(Base):
    __tablename__ = "entities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_pk: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(20), index=True)  # device|application|error_code|location|urgency_keyword
    value: Mapped[str] = mapped_column(String(200))
    ticket: Mapped[Ticket] = relationship(back_populates="entities")


class RoutingLog(Base):
    __tablename__ = "routing_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_pk: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    step: Mapped[str] = mapped_column(String(30))
    from_queue: Mapped[str | None] = mapped_column(String(40))
    to_queue: Mapped[str | None] = mapped_column(String(40))
    confidence: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)


class Incident(Base):
    """Major incident (ITIL): P1 parent record; child tickets link via tickets.incident_id.

    SLA/MTTR for a major incident is measured on THIS record once, not per child ticket.
    """
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(30))
    priority: Mapped[str] = mapped_column(String(3), default="P1")
    status: Mapped[str] = mapped_column(String(20), default="Open")
    detected_at: Mapped[datetime] = mapped_column(DateTime)
    window_start: Mapped[datetime | None] = mapped_column(DateTime)
    window_end: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    ticket_count: Mapped[int] = mapped_column(Integer, default=0)
    distinct_requesters: Mapped[int] = mapped_column(Integer, default=0)
    seed_ticket_id: Mapped[str | None] = mapped_column(String(32))
    summary: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base):
    """Append-only record of every automated decision, with a reason."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    ticket_id: Mapped[str | None] = mapped_column(String(32), index=True)
    actor: Mapped[str] = mapped_column(String(30))  # system|llm|agent:<name>
    step: Mapped[str] = mapped_column(String(30), index=True)
    decision: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[str | None] = mapped_column(Text)  # JSON blob


class Feedback(Base):
    """Agent corrections; feed scripts/retrain_with_feedback.py."""
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(String(32), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    agent: Mapped[str | None] = mapped_column(String(60))
    corrected_category: Mapped[str | None] = mapped_column(String(30))
    corrected_ticket_type: Mapped[str | None] = mapped_column(String(20))
    corrected_priority: Mapped[str | None] = mapped_column(String(3))
    comment: Mapped[str | None] = mapped_column(Text)
    used_in_training: Mapped[bool] = mapped_column(Boolean, default=False)
