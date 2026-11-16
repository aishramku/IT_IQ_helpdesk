"""Shared ITSM constants (categories, teams, SLA targets, priority matrix).

Kept dependency-free so the data generator, pipeline, dashboard and tests all
import the same single source of truth.
"""
from __future__ import annotations

CATEGORIES = ["Hardware", "Network", "Access/Password", "Software", "Email", "Printer"]
TICKET_TYPES = ["Incident", "Service Request"]  # ITIL: break/fix vs standard request
PRIORITIES = ["P1", "P2", "P3", "P4"]

CATEGORY_TEAM = {
    "Hardware": "Desktop Support",
    "Printer": "Desktop Support",
    "Network": "Network Operations",
    "Access/Password": "Identity & Access",
    "Software": "Application Support",
    "Email": "Messaging (M365)",
}
TEAMS = sorted(set(CATEGORY_TEAM.values()))

QUEUE_NEEDS_REVIEW = "Needs Review"  # human-in-the-loop (low confidence)
QUEUE_SECURITY = "Security Review"  # suspicious tickets never auto-assigned

# ITIL SLA resolution targets in (calendar) hours.
SLA_HOURS = {"P1": 4, "P2": 8, "P3": 24, "P4": 72}

# ITIL priority matrix: (impact, urgency) -> priority. 1 = high, 3 = low.
PRIORITY_MATRIX = {
    (1, 1): "P1", (1, 2): "P2", (1, 3): "P3",
    (2, 1): "P2", (2, 2): "P3", (2, 3): "P4",
    (3, 1): "P3", (3, 2): "P4", (3, 3): "P4",
}

CORPORATE_DOMAIN = "acmecorp.com"

LOCATIONS = {
    # name: (code, headcount weight)
    "Chennai-OMR": ("OMR", 0.24),
    "Bengaluru-Tech Park": ("BLR", 0.26),
    "Mumbai-BKC": ("BKC", 0.16),
    "Hyderabad-Hitech": ("HYD", 0.14),
    "Pune-Hinjewadi": ("PUN", 0.12),
    "Gurgaon-Cyber Hub": ("GGN", 0.08),
}

DEPARTMENTS = {
    "Engineering": 0.24, "Sales": 0.16, "Finance": 0.12, "Operations": 0.16,
    "HR": 0.07, "Marketing": 0.08, "Legal": 0.04, "Customer Support": 0.13,
}
