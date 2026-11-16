"""Social-engineering detector: urgency + authority + credential-request (+ sender domain).

A ticket is flagged when the weighted signals reach THRESHOLD. Any ONE signal alone
(e.g. a legitimately urgent VP, or an ordinary "please reset my password") stays below it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.security.sender_domain import classify_sender

_TITLES = r"(ceo|cfo|cto|coo|md|managing director|director|vp|vice president|head of [a-z]+|compliance head|it director|boss|chairman|president)"
SIGNALS: list[tuple[str, re.Pattern, float]] = [
    ("urgency", re.compile(r"\b(urgent|immediately|right now|right away|asap|no time|cannot wait|do it now|today)\b", re.I), 0.2),
    ("authority_claim", re.compile(rf"\b(i am|i'm|this is|as)\s+(the\s+|a\s+|an\s+|new\s+)?{_TITLES}\b|\b(the|my)\s+{_TITLES}\s+(has\s+)?(asked|said|wants|told|approved)\b|"
                                   rf"\bfor the\s+{_TITLES}\b|\bboss said\b|\bfrom the\s+{_TITLES}\b|\bvendor support here\b", re.I), 0.25),
    ("credential_exfiltration", re.compile(r"\bsend\b[^.\n]{0,25}\b(it|the new one|me)\b[^.\n]{0,30}\b(personal|gmail|my email|by email|by reply|email)\b|"
                                           r"\b(send|email|share|give|read out|reply with)\b[^.\n]{0,30}\b(the |your |a |my )?(new |temporary |admin )?(passwords?|credentials?)\b(?!\s+(reset|link))|"
                                           r"\bpasswords? sent to me\b|\bread it out\b", re.I), 0.35),
    ("verification_bypass", re.compile(r"\b(skip|bypass|without|no time for|cannot wait for|no need for|do not|don't)\b[^.\n]{0,15}\b(mfa|verification|verify|approval|callback|call me|escalate)\b|"
                                        r"\bno approval needed\b", re.I), 0.35),
    ("privileged_request", re.compile(r"\b(disable|remove|turn off)\b[^.\n]{0,15}\bmfa\b|\bmfa disabled\b|\bdomain admins?\b|\badmin(istrator)? (credentials|passwords?|access)\b|"
                                      r"\bunlock(ed)?\b[^.\n]{0,40}\b(ceo|md|his|her)\b|\baccess to the (ceo|md)\b|\bgive me access to the mailbox\b", re.I), 0.3),
]
DOMAIN_WEIGHT = {"lookalike": 0.4, "freemail": 0.25, "external": 0.25, "internal": 0.0}
THRESHOLD = 0.6


@dataclass
class SEResult:
    flagged: bool
    score: float
    signals: list[str] = field(default_factory=list)
    sender_class: str = "internal"


def detect_social_engineering(text: str, sender_email: str, corporate_domain: str) -> SEResult:
    hits = [(n, w) for n, rx, w in SIGNALS if rx.search(text)]
    sender = classify_sender(sender_email, corporate_domain)
    score = sum(w for _, w in hits)
    names = [n for n, _ in hits]
    # A foreign sender is only suspicious *in combination* with a content signal.
    if sender != "internal" and hits:
        score += DOMAIN_WEIGHT[sender]
        names.append(f"sender_{sender}")
    score = round(min(1.0, score), 2)
    return SEResult(score >= THRESHOLD, score, names, sender)
