"""Test setup: isolated temp database (set BEFORE any app import) + helpers."""
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="triageiq_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmp, 'test.db').as_posix()}"
os.environ["USE_LLM"] = "false"
os.environ["CONFIDENCE_THRESHOLD"] = "0.85"

import pytest  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.models import Base, Ticket  # noqa: E402

T0 = datetime(2026, 10, 6, 10, 0, 0)


@pytest.fixture()
def session():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()


def make_ticket(s, n: int, email: str, text: str, minutes: float = 0, category: str | None = "Email", **kw) -> Ticket:
    fields = dict(ticket_id=f"TCK-T{n:05d}", created_at=T0 + timedelta(minutes=minutes), requester_email=email, subject=text[:40],
                  raw_body=text, clean_text=text, category=category, priority="P3", status="New")
    t = Ticket(**{**fields, **kw})
    s.add(t)
    s.flush()
    return t
