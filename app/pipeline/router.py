"""Step 6 - Route: category -> resolver team, with human-in-the-loop gates."""
from __future__ import annotations

from dataclasses import dataclass

from app.constants import CATEGORY_TEAM, QUEUE_NEEDS_REVIEW, QUEUE_SECURITY


@dataclass
class RouteDecision:
    queue: str
    auto_assigned: bool
    reason: str


def route(category: str, confidence: float, threshold: float, security_flag: str | None = None) -> RouteDecision:
    """Order matters: security > low confidence > auto-assign."""
    if security_flag:
        return RouteDecision(QUEUE_SECURITY, False, f"security flag '{security_flag}': never auto-assigned")
    if confidence < threshold:
        return RouteDecision(QUEUE_NEEDS_REVIEW, False, f"confidence {confidence:.2f} < threshold {threshold:.2f}: human review")
    return RouteDecision(CATEGORY_TEAM[category], True, f"confidence {confidence:.2f} >= {threshold:.2f}: auto-assigned to {CATEGORY_TEAM[category]}")
