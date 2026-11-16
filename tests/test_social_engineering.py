import pytest

from app.security.sender_domain import classify_sender
from app.security.social_engineering import detect_social_engineering

CORP = "acmecorp.com"


@pytest.mark.parametrize("email,expected", [
    ("a.b@acmecorp.com", "internal"), ("x@gmail.com", "freemail"), ("ceo@acmecorp.co", "lookalike"), ("ceo@acme-corp.com", "lookalike"),
    ("ceo@acrnecorp.com", "lookalike"), ("ceo@acmec0rp.com", "lookalike"), ("ceo@acmecorp-support.com", "lookalike"), ("v@randomvendor.io", "external")])
def test_sender_classification(email, expected):
    assert classify_sender(email, CORP) == expected


def test_ceo_credential_request_flagged():
    t = "I am the CEO. Reset my password immediately and send the new one to my personal email. No time for verification."
    r = detect_social_engineering(t, "rajesh.menon@acmecorp.com", CORP)
    assert r.flagged and "credential_exfiltration" in r.signals


def test_lookalike_domain_pushes_borderline_over_threshold():
    t = "Vendor support here. We need your VPN credentials today. Reply with your password."
    assert detect_social_engineering(t, "support@acmecorp-support.com", CORP).flagged
    # same ask from an internal sender with no authority claim stays below the threshold (needs combined signals)
    assert not detect_social_engineering(t.replace("Vendor support here. ", ""), "support@acmecorp.com", CORP).flagged


@pytest.mark.parametrize("text", [
    "I forgot my password and need it reset please",
    "please send me a password reset link, i dont remember my password",
    "This is the Director Finance. I have a board presentation in 30 minutes and my laptop will not boot. Extremely urgent, send someone.",
    "Please reset my password ASAP, I am locked out of my laptop and have a client demo at 3.",
])
def test_legitimate_urgent_or_credential_tickets_not_flagged(text):
    assert not detect_social_engineering(text, "priya.rao@acmecorp.com", CORP).flagged


def test_foreign_domain_alone_is_not_enough():
    assert not detect_social_engineering("my printer is jammed", "someone@gmail.com", CORP).flagged
