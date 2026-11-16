"""Step 5 - Prioritise: ITIL Impact x Urgency -> P1..P4 (rules documented in docs/priority_matrix.md).

Design rule: ticket TEXT never sets a priority directly. Phrases like "set priority P1" are
ignored; only observable scope/urgency cues feed the matrix, and tickets flagged by the
security screen are capped so an attacker cannot escalate by wording.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.constants import PRIORITY_MATRIX

WIDE = re.compile(r"\b(everyone|entire office|all users|multiple users|whole office|across the location|everybody|all of us)\b", re.I)
TEAM = re.compile(r"\b(whole team|my team|department|colleagues|others (?:on|in|have)|same (?:issue|problem) for others|\d of us|few of us|our floor|same here)\b", re.I)
# business-critical services: one impact level higher even for a single user
CRITICAL = re.compile(r"\b(vpn|globalprotect)\b|\boutlook\b.{0,60}\b(disconnected|not connecting|send or receive|trying to connect)\b|"
                      r"\b(cannot|can't|unable to) (?:send|receive|access)\b.{0,30}\b(emails?|mails?|mailbox)\b", re.I)
URG_LOW = re.compile(r"\b(no rush|whenever you get a chance|not urgent|low priority|can be done this week|whenever)\b", re.I)
URG_HIGH = re.compile(r"\b(cannot work|can't work|unable to work|blocking me|blocked|client call|deadline|asap|urgent|urgently|"
                      r"immediately|stopped|production work|cannot do any work)\b", re.I)
URG_MED = re.compile(r"\b(productivity|slowing me|on and off|by tomorrow|intermittent|slow)\b", re.I)


@dataclass
class PriorityResult:
    impact: int
    urgency: int
    priority: str
    reasons: list[str]


def compute(text: str, ticket_type: str | None = None, capped: bool = False) -> PriorityResult:
    reasons: list[str] = []
    if WIDE.search(text):
        impact, why = 1, "wide scope (everyone/entire office)"
    elif TEAM.search(text):
        impact, why = 2, "team/department scope"
    else:
        impact, why = 3, "single user"
    reasons.append(f"impact={impact} ({why})")
    if CRITICAL.search(text) and impact > 1:
        impact -= 1
        reasons.append(f"impact raised to {impact}: business-critical service (VPN/email)")

    if URG_LOW.search(text):
        urgency, why = 3, "low-urgency wording"
    elif URG_HIGH.search(text):
        urgency, why = 1, "work-stoppage/deadline wording"
    elif URG_MED.search(text):
        urgency, why = 2, "degraded-service wording"
    else:
        urgency, why = (3, "service request default") if ticket_type == "Service Request" else (2, "incident default")
    reasons.append(f"urgency={urgency} ({why})")

    pr = PRIORITY_MATRIX[(impact, urgency)]
    if capped and pr in ("P1", "P2"):
        reasons.append(f"capped {pr}->P3: security-flagged ticket cannot escalate")
        pr = "P3"
    return PriorityResult(impact, urgency, pr, reasons)
