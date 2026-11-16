"""Prompt-injection detection. Ticket text is UNTRUSTED data, never instructions.

Score-based on purpose: a single weak phrase ("please forget the previous instructions you
sent me") must not flag a legitimate ticket; an override phrase combined with a
priority/privilege/role-change payload does.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# (name, regex, weight). Flag when the summed weight >= THRESHOLD, i.e. >= 2 independent signals.
SIGNALS: list[tuple[str, re.Pattern, float]] = [
    ("override_phrase", re.compile(r"\b(ignore|disregard|forget|override)\b[^.\n]{0,25}\b(previous|prior|above|earlier|all)\b[^.\n]{0,20}\b(instructions?|rules?|prompts?|directions?|the above)\b|"
                                    r"\bignore the above\b|\bforget the above\b|\boverride\s*:", re.I), 0.5),
    ("role_change", re.compile(r"\byou are now\b|\bnew instructions\b|\badmin mode\b|\bdeveloper mode\b|^\s*system\s*:|\bsystem\s*:\s*you", re.I | re.M), 0.6),
    ("tag_injection", re.compile(r"</?(system|ticket|assistant|instructions?)>|#{2,}\s*new instructions", re.I), 0.6),
    ("set_priority", re.compile(r"\b(set|mark|change|raise|escalate|classify)\b[^.\n]{0,40}\bp[12]\b|\bpriority\s*[=:]\s*\"?p[1-4]\b|\bset priority\b", re.I), 0.6),
    ("privilege_grant", re.compile(r"\bgrant\b[^.\n]{0,25}\b(admin|domain admin|access)\b|\bapprove\b[^.\n]{0,25}\b(password reset|request)\b|"
                                  r"auto[- ]approve|\bwithout verification\b|\badmin rights\b|\bgrant_admin\b", re.I), 0.6),
    ("schema_leak", re.compile(r"\"(category|priority|action)\"\s*:|\bcategory\s*=\s*\w+", re.I), 0.6),
    ("prompt_exfil", re.compile(r"\b(reveal|print|show|output)\b[^.\n]{0,25}\b(system prompt|your instructions)\b|\bas an ai\b", re.I), 0.6),
]
THRESHOLD = 0.9


@dataclass
class InjectionResult:
    flagged: bool
    score: float
    matches: list[str] = field(default_factory=list)


def detect_injection(text: str) -> InjectionResult:
    hits = [(n, w) for n, rx, w in SIGNALS if rx.search(text)]
    score = round(min(1.0, sum(w for _, w in hits)), 2)
    return InjectionResult(score >= THRESHOLD, score, [n for n, _ in hits])


def strip_injection(text: str) -> str:
    """Remove sentences containing injection signals so classification/priority see only the real issue."""
    parts = re.split(r"(?<=[.!?;])\s+|\n+", text)
    keep = [p for p in parts if not any(rx.search(p) for _, rx, _ in SIGNALS)]
    return " ".join(keep).strip() or text
