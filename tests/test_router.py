import pytest

from app.constants import CATEGORY_TEAM, QUEUE_NEEDS_REVIEW, QUEUE_SECURITY
from app.pipeline.router import route


@pytest.mark.parametrize("cat,team", CATEGORY_TEAM.items())
def test_category_maps_to_team(cat, team):
    assert route(cat, 0.99, 0.85).queue == team


def test_threshold_boundary():
    assert route("Network", 0.85, 0.85).auto_assigned
    d = route("Network", 0.8499, 0.85)
    assert d.queue == QUEUE_NEEDS_REVIEW and not d.auto_assigned


def test_security_flag_overrides_confidence():
    d = route("Access/Password", 0.99, 0.85, "social_engineering")
    assert d.queue == QUEUE_SECURITY and not d.auto_assigned


def test_reason_is_explained():
    assert "confidence" in route("Email", 0.5, 0.85).reason
