"""Step 2 - Clean: strip signatures/disclaimers, normalise, redact PII.

PII is redacted BEFORE anything downstream (classifier, entities, KB, LLM, clean_text
storage) sees the text. Only `tickets.raw_body` keeps the original (restricted column).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

EMAIL_RE = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
EMP_ID_RE = re.compile(r"\bEMP[-\s]?\d{4,6}\b", re.I)
# 9+ digits, optionally with +CC and separators: covers Indian mobiles and intl formats
PHONE_RE = re.compile(r"(?<![\w-])(?:\+\d{1,3}[\s-]?)?(?:\d{5}[\s-]?\d{5}|\(?\d{3,5}\)?[\s-]?\d{3,5}[\s-]?\d{3,5})(?![\w-])")

_SIGNOFF_RE = re.compile(
    r"^\s*(thanks|thank you|regards|best regards|kind regards|warm regards|cheers|thanks\s*(&|and)\s*regards|--+|__+)\s*[,!.]*\s*$",
    re.I)
_FOOTER_MARKERS = re.compile(
    r"(confidentiality notice|this message is intended only|please consider the environment|sent from my |get outlook for )", re.I)
_REPLY_PREFIX = re.compile(r"^\s*((re|fw|fwd)\s*:\s*)+", re.I)


@dataclass
class CleanResult:
    text: str  # "<subject>. <body>" cleaned + redacted, single line
    redactions: dict[str, int] = field(default_factory=dict)
    signature_stripped: bool = False


def redact_pii(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for label, rx in (("EMAIL", EMAIL_RE), ("EMP_ID", EMP_ID_RE), ("PHONE", PHONE_RE)):
        text, n = rx.subn(f"[{label}]", text)
        if n:
            counts[label] = n
    return text, counts


def strip_signature(text: str) -> tuple[str, bool]:
    """Cut at the first disclaimer/footer or sign-off line (keeps at least the first line)."""
    m = _FOOTER_MARKERS.search(text)
    cut = text[: m.start()] if m and m.start() > 0 else text
    stripped = len(cut) != len(text)
    lines = cut.splitlines()
    for i, line in enumerate(lines):
        if i > 0 and _SIGNOFF_RE.match(line):
            lines, stripped = lines[:i], True
            break
    return "\n".join(lines), stripped


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("\r", "")
    text = re.sub(r"([!?.,])\1+", r"\1", text)  # "urgent!!!" -> "urgent!" (shouting must not change meaning)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_ticket(subject: str, body: str) -> CleanResult:
    body_nosig, stripped = strip_signature(body or "")
    subject = _REPLY_PREFIX.sub("", subject or "")
    text, counts = redact_pii(f"{subject}. {body_nosig}")
    return CleanResult(text=normalize(text), redactions=counts, signature_stripped=stripped)
