"""Sender-domain analysis: internal / free-mail / look-alike / external."""
from __future__ import annotations

import Levenshtein

FREEMAIL = {"gmail.com", "outlook.com", "yahoo.com", "hotmail.com", "proton.me", "icloud.com"}
_HOMOGLYPH = str.maketrans({"0": "o", "1": "l", "5": "s", "3": "e"})


def _norm(domain: str) -> str:
    return domain.lower().replace("rn", "m").translate(_HOMOGLYPH).replace("-", "")


def classify_sender(email: str, corporate_domain: str) -> str:
    """internal | freemail | lookalike | external"""
    domain = email.rsplit("@", 1)[-1].strip().lower()
    corp = corporate_domain.lower()
    if domain == corp:
        return "internal"
    if domain in FREEMAIL:
        return "freemail"
    base = corp.split(".")[0]
    n = _norm(domain)
    if (Levenshtein.distance(domain, corp) <= 3 or _norm(corp) in n or base in domain
            or Levenshtein.distance(n, _norm(corp)) <= 1):
        return "lookalike"
    return "external"
