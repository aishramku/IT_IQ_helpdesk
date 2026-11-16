from app.intelligence.incidents import check_incident
from app.models import AuditLog, Incident
from conftest import make_ticket

TXT = ["outlook is not connecting, cannot send or receive any emails since this morning",
       "outlook is disconnected, cannot send or receive any emails since this morning",
       "outlook not connecting, cannot send or receive emails at all since this morning"]


def _feed(session, n_tickets, n_users):
    out = []
    for i in range(n_tickets):
        t = make_ticket(session, i, f"user{i % n_users}@acmecorp.com", TXT[i % 3], minutes=i * 0.8)
        out.append((t, check_incident(session, t)))
    return out


def test_ten_distinct_requesters_open_one_p1_incident(session):
    res = _feed(session, 12, 12)
    assert session.query(Incident).count() == 1
    inc = session.query(Incident).one()
    assert inc.priority == "P1" and inc.distinct_requesters >= 10
    assert all(t.priority == "P1" and t.incident_id == inc.incident_id for t, _ in res[:10])
    assert res[8][1] is None and res[9][1] is not None  # detected exactly on the 10th distinct requester


def test_nine_distinct_requesters_do_not_open_incident(session):
    _feed(session, 9, 9)
    assert session.query(Incident).count() == 0


def test_one_user_spamming_cannot_fake_an_incident(session):
    _feed(session, 15, 3)
    assert session.query(Incident).count() == 0


def test_late_reporter_joins_open_incident(session):
    _feed(session, 10, 10)
    t = make_ticket(session, 99, "late@acmecorp.com", TXT[0], minutes=25)
    inc = check_incident(session, t)
    assert inc is not None and t.incident_id == inc.incident_id and session.query(Incident).count() == 1


def test_unrelated_category_not_linked(session):
    _feed(session, 10, 10)
    t = make_ticket(session, 98, "p@acmecorp.com", "printer on third floor is jammed", 9, "Printer")
    assert check_incident(session, t) is None


def test_reprioritisation_is_audited_old_to_new(session):
    _feed(session, 10, 10)
    rows = session.query(AuditLog).filter_by(step="reprioritisation").all()
    assert len(rows) == 10
    assert rows[0].decision == "priority P3 -> P1" and "INC-0001" in rows[0].reason
