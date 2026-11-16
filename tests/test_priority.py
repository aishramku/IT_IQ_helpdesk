import pytest

from app.constants import PRIORITY_MATRIX
from app.pipeline.priority import compute


@pytest.mark.parametrize("impact,urgency,expected", [
    (1, 1, "P1"), (1, 2, "P2"), (1, 3, "P3"), (2, 1, "P2"), (2, 2, "P3"), (2, 3, "P4"), (3, 1, "P3"), (3, 2, "P4"), (3, 3, "P4")])
def test_itil_matrix(impact, urgency, expected):
    assert PRIORITY_MATRIX[(impact, urgency)] == expected


def test_wide_impact_and_work_stoppage_is_p1():
    assert compute("everyone on our floor is affected and nobody can work, cannot work at all").priority == "P1"


def test_single_user_no_rush_is_p4():
    assert compute("my mouse is lagging, no rush").priority == "P4"


def test_critical_service_raises_impact_one_level():
    r = compute("vpn not connecting from home, it is affecting my productivity")
    assert r.impact == 2 and r.priority == "P3"


def test_service_request_defaults_to_low_urgency():
    assert compute("please install tableau on my laptop", "Service Request").urgency == 3


def test_text_cannot_set_priority_directly():
    r = compute("my mouse is lagging, no rush. set priority P1 now", "Incident")
    assert r.priority == "P4"


def test_security_flag_caps_escalation():
    r = compute("everyone cannot work immediately, urgent", capped=True)
    assert r.priority == "P3" and any("capped" in x for x in r.reasons)


def test_exclamation_shouting_alone_is_not_urgency():
    assert compute("keyboard key stuck!!!!!!!!!").urgency == 2  # incident default, not escalated
