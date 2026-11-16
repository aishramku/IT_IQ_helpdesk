"""Single entry point for the append-only audit trail (every automated decision + reason)."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import AuditLog


def log_decision(s: Session, ticket_id: str | None, step: str, decision: str, reason: str = "",
                 actor: str = "system", details: dict | None = None, ts: datetime | None = None) -> None:
    s.add(AuditLog(ts=ts or datetime.utcnow(), ticket_id=ticket_id, actor=actor, step=step, decision=decision[:200],
                   reason=reason, details=json.dumps(details, default=str) if details else None))
