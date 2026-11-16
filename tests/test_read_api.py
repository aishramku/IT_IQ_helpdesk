"""Read API used by the web frontend. Runs against the isolated temp DB from conftest (no model needed)."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import AuditLog, Entity, Incident
from conftest import T0, make_ticket

client = TestClient(app)


@pytest.fixture()
def seeded(session):
    a = make_ticket(session, 1, "a@acmecorp.com", "vpn will not connect from home", 0, "Network", ticket_type="Incident", confidence=0.93,
                    routed_queue="Network Operations", status="Assigned", priority="P2", location="Chennai-OMR", kb_article_id="KB0006",
                    action_tier="SAFE", action_status="kb_suggested")
    b = make_ticket(session, 2, "b@acmecorp.com", "please reset my password", 5, "Access/Password", ticket_type="Service Request", confidence=0.7,
                    routed_queue="Needs Review", status="Needs Review", priority="P3", action_tier="REQUIRES_APPROVAL", action_status="verification_required")
    c = make_ticket(session, 3, "ceo@acmecorp.co", "reset my password immediately and send it", 9, "Access/Password", ticket_type="Service Request",
                    confidence=0.5, routed_queue="Security Review", status="Security Review", priority="P3", security_flag="social_engineering",
                    sender_domain="acmecorp.co", action_tier="REQUIRES_APPROVAL", action_status="blocked_security_review")
    session.add(Entity(ticket_pk=a.id, entity_type="application", value="VPN"))
    session.add(AuditLog(ts=T0, ticket_id=a.ticket_id, actor="system", step="priority", decision="P2", reason="impact=3 (single user); urgency=2"))
    session.add(Incident(incident_id="INC-0001", title="Major incident: Email", category="Email", priority="P1", status="Open", detected_at=T0 + timedelta(minutes=3),
                         window_start=T0, window_end=T0 + timedelta(minutes=2), ticket_count=3, distinct_requesters=3))
    session.flush()
    for i in range(3):  # a tiny incident
        k = make_ticket(session, 10 + i, f"u{i}@acmecorp.com", "outlook disconnected", i, "Email", incident_id="INC-0001", location="Pune-Hinjewadi")
    session.commit()
    return a, b, c


def test_list_filters_search_pagination_and_queue_counts(seeded):
    r = client.get("/tickets", params={"queue": "Needs Review"}).json()
    assert r["total"] == 1 and r["items"][0]["category"] == "Access/Password"
    assert r["queue_counts"]["Network Operations"] == 1 and r["queue_counts"]["Security Review"] == 1  # counts ignore the queue filter
    assert client.get("/tickets", params={"search": "vpn"}).json()["total"] == 1
    assert client.get("/tickets", params={"priority": "P2", "ticket_type": "Incident"}).json()["total"] == 1
    p = client.get("/tickets", params={"page": 2, "page_size": 2}).json()
    assert p["page"] == 2 and len(p["items"]) == 2 and p["total"] == 6
    assert client.get("/tickets", params={"page_size": 1000}).status_code == 422  # bounded


def test_ticket_detail_has_the_why_panel_fields(seeded):
    d = client.get("/tickets/TCK-T00001").json()
    assert d["classification"]["confidence"] == 0.93 and d["entities"] == [{"type": "application", "value": "VPN"}]
    assert d["priority_detail"]["reasons"][0].startswith("impact=3") and d["kb"]["id"] == "KB0006"
    assert d["audit_log"][0]["step"] == "priority" and d["ticket"]["sla_hours"] == 8
    s = client.get("/tickets/TCK-T00003").json()["security"]
    assert s["flag"] == "social_engineering" and s["sender_class"] == "lookalike"
    assert client.get("/tickets/NOPE").status_code == 404


def test_raw_body_is_restricted_and_audited(seeded, session):
    r = client.get("/tickets/TCK-T00002/raw", params={"agent": "alice"}).json()
    assert "password" in r["raw_body"] and "Restricted" in r["warning"]
    row = session.query(AuditLog).filter_by(step="restricted_access").one()
    assert row.actor == "agent:alice"


def test_agent_actions_never_execute_and_validate(seeded):
    assert client.post("/tickets/TCK-T00001/actions", json={"action": "approve_action"}).status_code == 409  # SAFE: nothing to approve
    assert client.post("/tickets/TCK-T00003/actions", json={"action": "approve_action"}).status_code == 409  # security-flagged: blocked
    ok = client.post("/tickets/TCK-T00002/actions", json={"action": "approve_action", "agent": "alice"}).json()
    assert ok["action_status"] == "approved_pending_execution"
    done = client.post("/tickets/TCK-T00001/actions", json={"action": "mark_resolved"}).json()
    assert done["status"] == "Resolved" and done["resolved_at"]
    assert client.post("/tickets/TCK-T00001/actions", json={"action": "delete_everything"}).status_code == 422


def test_incident_list_and_detail(seeded):
    lst = client.get("/incidents").json()
    assert lst[0]["incident_id"] == "INC-0001" and lst[0]["locations"] == {"Pune-Hinjewadi": 3}
    d = client.get("/incidents/INC-0001").json()
    assert len(d["children"]) == 3 and d["timeline"][-1]["cumulative"] == 3 and d["detection_lag_minutes"] == 3.0
    assert client.get("/incidents/INC-9999").status_code == 404


def test_feedback_shape_and_count(seeded):
    r = client.post("/feedback", json={"ticket_id": "TCK-T00002", "agent": "alice", "corrected_category": "Software"})
    assert r.status_code == 201 and r.json() == {"status": "recorded", "feedback_total": 1}
    assert client.post("/feedback", json={"ticket_id": "TCK-T00002", "corrected_category": "Bogus"}).status_code == 422
    assert client.get("/tickets/TCK-T00002").json()["feedback"][0]["corrected_category"] == "Software"


@pytest.mark.parametrize("path", ["overview", "kpis", "trends", "insights", "impact", "model", "security"])
def test_analytics_endpoints_ok_on_empty_db(session, path):
    assert client.get(f"/analytics/{path}").status_code == 200


@pytest.mark.parametrize("path", ["overview", "kpis", "trends", "insights", "impact", "model", "security"])
def test_analytics_endpoints_ok_with_data(seeded, path):
    r = client.get(f"/analytics/{path}")
    assert r.status_code == 200
    assert "NaN" not in r.text  # strict JSON


def test_overview_date_range_and_security_payload(seeded):
    assert client.get("/analytics/overview").json()["total"] == 6
    assert client.get("/analytics/overview", params={"start": "2030-01-01"}).json()["total"] == 0
    sec = client.get("/analytics/security").json()
    assert sec["counts"] == {"social_engineering": 1} and sec["auto_executed_actions"] == 0


def test_cors_allows_vite_origin():
    r = client.options("/tickets", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
