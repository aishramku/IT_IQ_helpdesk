"""Pydantic request/response models for the API."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class TicketIn(BaseModel):
    requester_email: EmailStr
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    department: str | None = None
    location: str | None = None


class EmailWebhookIn(BaseModel):
    """Raw inbound-email payload (shape modelled on common providers' inbound-parse webhooks)."""
    sender: str = Field(alias="from")  # "Jane Doe <jane.doe@acmecorp.com>" or bare address
    to: str | None = None
    subject: str = ""
    text: str | None = None
    html: str | None = None
    message_id: str | None = None
    received_at: datetime | None = None
    model_config = {"populate_by_name": True}


class TicketOut(BaseModel):
    ticket_id: str
    status: str
    category: str | None
    ticket_type: str | None
    confidence: float | None
    priority: str | None
    routed_queue: str | None
    kb_article_id: str | None
    kb_url: str | None
    action_tier: str | None
    action_status: str | None
    security_flag: str | None
    incident_id: str | None
    duplicate_of: str | None
    reason: str | None = None


class FeedbackIn(BaseModel):
    ticket_id: str
    agent: str | None = None
    corrected_category: Literal["Hardware", "Network", "Access/Password", "Software", "Email", "Printer"] | None = None
    corrected_ticket_type: Literal["Incident", "Service Request"] | None = None
    corrected_priority: Literal["P1", "P2", "P3", "P4"] | None = None
    comment: str | None = None
