"""Step 4 - Extract entities: devices/assets, applications, error codes, location, urgency keywords.

Regex handles the structured tokens; spaCy (en_core_web_sm) adds GPE/FAC place names.
Runs on PII-redacted clean_text only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

DEVICE_RE = re.compile(r"\b(?:LT|DT|LAPTOP|DESKTOP)-[A-Z]{2,4}-\d{3,5}\b|\bPRN-[A-Z]{2,4}-\d[A-Z]?-?\d{1,3}\b", re.I)
ERROR_RES = [
    re.compile(r"\b0x[0-9A-Fa-f]{6,8}\b"), re.compile(r"\bAADSTS\d{4,6}\b"), re.compile(r"\bERR_[A-Z_]{4,}\b"),
    re.compile(r"\bHTTP\s?\d{3}\b", re.I), re.compile(r"\b(?:error|code|exception)\s+(?:code\s+)?\d{2,5}\b", re.I),
    re.compile(r"\bINACCESSIBLE_BOOT_DEVICE\b"),
]
APPS = ["Outlook", "Excel", "Word", "PowerPoint", "Teams", "SAP GUI", "SAP", "Salesforce", "Tableau", "Chrome", "Zoom",
        "Adobe Acrobat", "Power BI", "VS Code", "Jira", "Confluence", "SharePoint", "Workday", "GlobalProtect", "VPN",
        "Microsoft Office", "Office", "Windows", "Docker Desktop", "Postman", "Visio", "Python", "Authenticator", "OneDrive"]
APP_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, APPS), key=len, reverse=True)) + r")\b", re.I)
LOCATION_RE = re.compile(
    r"\b(Chennai|OMR|Bengaluru|Bangalore|BLR|Mumbai|BKC|Hyderabad|Hitech|Pune|Hinjewadi|Gurgaon|Cyber Hub|"
    r"\d(?:st|nd|rd|th) floor|ground floor)\b", re.I)
URGENCY_RE = re.compile(
    r"\b(urgent|urgently|asap|immediately|right now|cannot work|can't work|unable to work|blocking|blocked|deadline|"
    r"client call|production|critical|emergency|stopped working|no rush|not urgent|whenever|low priority)\b", re.I)


@dataclass(frozen=True)
class Ent:
    type: str  # device|application|error_code|location|urgency_keyword
    value: str


@lru_cache(maxsize=1)
def _nlp():
    try:
        import spacy
        return spacy.load("en_core_web_sm", disable=["parser", "lemmatizer", "attribute_ruler"])
    except Exception:  # model missing -> regex-only mode still works
        return None


def extract(text: str, use_spacy: bool = True) -> list[Ent]:
    out: dict[tuple[str, str], Ent] = {}

    def add(t: str, v: str) -> None:
        v = v.strip()
        if v:
            out.setdefault((t, v.lower()), Ent(t, v))

    for m in DEVICE_RE.finditer(text):
        add("device", m.group(0).upper())
    for rx in ERROR_RES:
        for m in rx.finditer(text):
            add("error_code", m.group(0))
    for m in APP_RE.finditer(text):
        add("application", m.group(1))
    for m in LOCATION_RE.finditer(text):
        add("location", m.group(1))
    for m in URGENCY_RE.finditer(text):
        add("urgency_keyword", m.group(1).lower())
    if use_spacy and (nlp := _nlp()) is not None:
        for ent in nlp(text).ents:
            if ent.label_ in ("GPE", "FAC", "LOC"):
                add("location", ent.text)
    return list(out.values())
