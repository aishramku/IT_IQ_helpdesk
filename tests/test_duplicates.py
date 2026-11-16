from datetime import timedelta

from app.intelligence.duplicates import check_duplicate
from conftest import T0, make_ticket

TXT = "outlook keeps showing disconnected and i cannot send or receive emails since morning"


def test_same_user_similar_text_within_24h_is_merged(session):
    a = make_ticket(session, 1, "a@acmecorp.com", TXT, 0)
    b = make_ticket(session, 2, "a@acmecorp.com", "still facing this issue any update " + TXT, 300)
    assert check_duplicate(session, b) is a
    assert b.duplicate_of == a.ticket_id and b.status == "Merged"


def test_different_requester_is_not_a_duplicate(session):
    make_ticket(session, 1, "a@acmecorp.com", TXT, 0)
    b = make_ticket(session, 2, "b@acmecorp.com", TXT, 5)
    assert check_duplicate(session, b) is None


def test_different_text_same_user_not_merged(session):
    make_ticket(session, 1, "a@acmecorp.com", TXT, 0)
    b = make_ticket(session, 2, "a@acmecorp.com", "please install tableau on my laptop for the analytics project", 60, "Software")
    assert check_duplicate(session, b) is None


def test_outside_24h_window_not_merged(session):
    make_ticket(session, 1, "a@acmecorp.com", TXT, 0)
    b = make_ticket(session, 2, "a@acmecorp.com", TXT, 0, created_at=T0 + timedelta(hours=25))
    assert check_duplicate(session, b) is None


def test_merge_writes_audit_row(session):
    from app.models import AuditLog
    make_ticket(session, 1, "a@acmecorp.com", TXT, 0)
    b = make_ticket(session, 2, "a@acmecorp.com", TXT, 30)
    check_duplicate(session, b)
    row = session.query(AuditLog).filter_by(step="duplicate_detection").one()
    assert "similarity" in row.reason
