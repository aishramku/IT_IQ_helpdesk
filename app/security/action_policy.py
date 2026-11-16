"""Automation safety tiers. The system NEVER executes account or access actions.

SAFE              -> may be automated (acknowledge, attach KB article)
REQUIRES_APPROVAL -> only produces a recommendation + a status for a human/verification step
There is deliberately no function here that performs a reset, unlock, grant or install.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SAFE = "SAFE"
REQUIRES_APPROVAL = "REQUIRES_APPROVAL"

# action -> (tier, status when proposed)
ACTIONS = {
    "acknowledge_ticket": (SAFE, "auto_acknowledged"),
    "send_kb_article": (SAFE, "kb_suggested"),
    "password_reset": (REQUIRES_APPROVAL, "verification_required"),  # simulated MFA / verified-channel callback
    "account_unlock": (REQUIRES_APPROVAL, "verification_required"),
    "mfa_reset": (REQUIRES_APPROVAL, "verification_required"),
    "access_grant": (REQUIRES_APPROVAL, "pending_approval"),
    "software_install": (REQUIRES_APPROVAL, "pending_approval"),
}
_PATTERNS = [
    ("mfa_reset", re.compile(r"\b(mfa|authenticator)\b.{0,40}\b(reset|new phone|not (working|sending))|\bnew phone\b", re.I)),
    ("password_reset", re.compile(r"\b(reset|forgot|expired|change)\b.{0,30}\bpassword\b|\bpassword\b.{0,30}\b(reset|expired|forgot)\b", re.I)),
    ("account_unlock", re.compile(r"\block(ed)?\s?out\b|\baccount\b.{0,20}\block(ed)?\b|\bunlock\b", re.I)),
    ("access_grant", re.compile(r"\b(access|permission|role|add me to|distribution list|shared mailbox)\b.{0,40}\b(request|need|please|give|grant)\b|"
                                r"\b(need|request|give me|grant)\b.{0,30}\b(access|permissions?)\b", re.I)),
    ("software_install", re.compile(r"\b(install|installation|licen[cs]e)\b", re.I)),
]


@dataclass
class ActionPlan:
    tier: str
    status: str
    safe_actions: list[str] = field(default_factory=list)
    approval_actions: list[str] = field(default_factory=list)
    note: str = ""


def plan_actions(text: str, category: str, ticket_type: str, has_kb: bool, security_flag: str | None) -> ActionPlan:
    safe = ["acknowledge_ticket"]
    if security_flag:  # suspicious: acknowledge only, everything else blocked pending Security review
        return ActionPlan(REQUIRES_APPROVAL, "blocked_security_review", safe, [], f"security flag {security_flag}: all actions suspended")
    if has_kb:
        safe.append("send_kb_article")
    needed = []
    if category == "Access/Password" or ticket_type == "Service Request":
        needed = [a for a, rx in _PATTERNS if rx.search(text)]
        if category == "Access/Password" and "mfa_reset" in needed and "password_reset" in needed:
            needed.remove("password_reset")
    if not needed:
        return ActionPlan(SAFE, "kb_suggested" if has_kb else "auto_acknowledged", safe, [])
    status = ACTIONS[needed[0]][1]
    return ActionPlan(REQUIRES_APPROVAL, status, safe, needed,
                      "never auto-executed: requires identity verification / approval" if status == "verification_required"
                      else "never auto-executed: requires owner/manager approval")
