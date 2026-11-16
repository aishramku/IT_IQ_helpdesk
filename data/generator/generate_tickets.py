"""Synthetic helpdesk ticket generator (seeded, reproducible).

    python -m data.generator.generate_tickets            # writes data/raw/tickets.csv

Produces ~3,000 messy tickets over 90 days with analytics-discoverable patterns:
  * VPN tickets spike on Monday 09:00-11:00 (4x sampling weight)
  * ONE email outage: 40 near-identical tickets from 40 distinct users in 14 minutes
  * Printer issues concentrated in one office (Chennai-OMR ~55%)
  * 30 same-requester duplicates (follow-ups within ~20h)
  * 12 social-engineering tickets (lookalike domain / free-mail / internal sender)
  * 8 prompt-injection tickets
  * 25 legitimate "decoys" (urgent execs, "please ignore my previous ticket") so
    detector false-positive rates are measurable
  * ~5% label noise, ~8% vague one-liners, typos, signatures, disclaimers, inline PII

Columns prefixed as ground truth (true_*, subtype, scenario, is_malicious,
attack_type, dup_of) are EVALUATION-ONLY: the pipeline never reads them.
"""
from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from app.constants import CATEGORIES, CATEGORY_TEAM, CORPORATE_DOMAIN, DEPARTMENTS, LOCATIONS, PRIORITY_MATRIX
from data.generator import templates as T

SEED = 42
START = datetime(2026, 8, 17)  # a Monday
DAYS = 90
END = START + timedelta(days=DAYS) - timedelta(minutes=1)  # "now" for the history
N_TOTAL = 3000
N_OUTAGE, N_DUP, N_SE, N_INJ, N_DEC_EXEC, N_DEC_IGN = 40, 30, 12, 8, 15, 10
OUTAGE_START = START + timedelta(days=50, hours=10, minutes=12)  # Tue 2026-10-06 10:12

CAT_WEIGHTS = {"Hardware": 0.17, "Network": 0.17, "Access/Password": 0.22, "Software": 0.19, "Email": 0.14, "Printer": 0.11}
DAY_W = [1.15, 1.0, 1.0, 1.0, 0.9, 0.12, 0.08]  # Mon..Sun
HOUR_W = [0.05, 0.03, 0.02, 0.02, 0.03, 0.08, 0.2, 0.5, 1.2, 2.2, 2.4, 1.9,
          1.1, 1.6, 1.9, 1.8, 1.4, 0.9, 0.4, 0.2, 0.12, 0.1, 0.08, 0.06]
PRINTER_HOTSPOT = ("Chennai-OMR", 0.55)
MISROUTE = {  # where a human L1 typically mis-sends a ticket (baseline)
    "Hardware": ["Application Support", "Network Operations"], "Printer": ["Network Operations", "Application Support"],
    "Network": ["Desktop Support", "Messaging (M365)"], "Access/Password": ["Application Support", "Messaging (M365)"],
    "Software": ["Desktop Support", "Identity & Access"], "Email": ["Network Operations", "Identity & Access"],
}
MEDIAN_H = {"P1": 2.5, "P2": 5.0, "P3": 13.0, "P4": 36.0}
FIRST = ("Aarav Vivaan Aditya Arjun Rohan Karthik Suresh Ramesh Vikram Rahul Amit Nikhil Sanjay Manoj Deepak Prakash Anil Gaurav "
         "Harish Naveen Priya Ananya Divya Kavya Meera Neha Pooja Sneha Lakshmi Sunita Anjali Deepa Shruti Swathi Nisha Ritu "
         "Isha Tara Radhika Sana Farah John Maria David Sarah Daniel Emma").split()
LAST = ("Sharma Verma Iyer Nair Menon Reddy Rao Patel Shah Gupta Singh Kumar Das Bose Chatterjee Pillai Krishnan Subramanian "
        "Narayan Joshi Kulkarni Desai Mehta Kapoor Malhotra Bhat Hegde Naidu Choudhary Agarwal Mishra Banerjee Khan Fernandes "
        "D'Souza Thomas Mathew George").split()
TITLES = {"Engineering": "Software Engineer", "Sales": "Account Executive", "Finance": "Finance Analyst", "Operations": "Operations Manager",
          "HR": "HR Business Partner", "Marketing": "Marketing Specialist", "Legal": "Legal Counsel", "Customer Support": "Support Lead"}
EXECS = [("Rajesh", "Menon", "Chief Executive Officer"), ("Ananya", "Iyer", "Chief Financial Officer"),
         ("Vikram", "Shah", "VP Sales"), ("Meera", "Nair", "Director Finance"),
         ("Arjun", "Rao", "VP Engineering"), ("Sunita", "Verma", "Head of HR")]
LOOKALIKES = ["acmecorp.co", "acme-corp.com", "acrnecorp.com", "acmec0rp.com", "acmecorp.com.co", "acmecorp-support.com"]
FREEMAIL = ["gmail.com", "outlook.com", "yahoo.com"]


class Emp:
    def __init__(self, i: int, first: str, last: str, dept: str, location: str, rng: random.Random, title: str | None = None):
        self.first, self.last, self.dept, self.location = first, last, dept, location
        self.name = f"{first} {last}"
        self.email = f"{first}.{last}".lower().replace("'", "") + f"@{CORPORATE_DOMAIN}"
        self.emp_id = f"EMP{10000 + i}"
        self.phone = rng.choice([f"9{rng.randint(10**8, 10**9 - 1)}", f"+91 9{rng.randint(10**8, 10**9 - 1)}",
                                 f"+91-9{rng.randint(10**8, 10**9 - 1)}"])
        self.ext = str(rng.randint(2000, 8999))
        self.title = title or TITLES[dept]


def weighted(rng: random.Random, mapping: dict) -> str:
    return rng.choices(list(mapping), weights=list(mapping.values()))[0]


def make_employees(rng: random.Random, n: int = 420) -> list[Emp]:
    loc_w = {k: v[1] for k, v in LOCATIONS.items()}
    emps: list[Emp] = []
    used = set()
    for i, (f, l, title) in enumerate(EXECS):
        used.add((f, l))
        emps.append(Emp(i, f, l, "Finance" if "Finance" in title or "Financial" in title else "Operations",
                        rng.choice(["Chennai-OMR", "Mumbai-BKC"]), rng, title))
    while len(emps) < n:
        f, l = rng.choice(FIRST), rng.choice(LAST)
        if (f, l) in used:
            continue
        used.add((f, l))
        emps.append(Emp(len(emps), f, l, weighted(rng, DEPARTMENTS), weighted(rng, loc_w), rng))
    return emps


class Sampler:
    """Hour-slot sampler over the 90 days; VPN gets a 4x Monday 09-11 boost."""

    def __init__(self) -> None:
        self.starts, w, wv = [], [], []
        for d in range(DAYS):
            day = START + timedelta(days=d)
            for h in range(24):
                base = DAY_W[day.weekday()] * HOUR_W[h]
                self.starts.append(day + timedelta(hours=h))
                w.append(base)
                wv.append(base * (4.0 if day.weekday() == 0 and h in (9, 10) else 1.0))
        self.cum, self.cum_vpn = self._cum(w), self._cum(wv)

    @staticmethod
    def _cum(ws: list[float]) -> list[float]:
        out, t = [], 0.0
        for x in ws:
            t += x
            out.append(t)
        return out

    def sample(self, rng: random.Random, vpn: bool = False) -> datetime:
        idx = rng.choices(range(len(self.starts)), cum_weights=self.cum_vpn if vpn else self.cum)[0]
        return self.starts[idx] + timedelta(seconds=rng.randint(0, 3599))


# ----------------------------------------------------------------------------- text helpers
class _Safe(dict):
    def __missing__(self, key: str) -> str:
        return ""


def fill(text: str, ctx: dict) -> str:
    return text.format_map(_Safe(ctx))


def apply_typos(rng: random.Random, text: str, rate: float) -> str:
    out = []
    for tok in text.split(" "):
        core = tok.strip(".,!?;:'\"()")
        if "{" in tok or len(core) < 5 or not core.isalpha() or core.isupper() or rng.random() >= rate:
            out.append(tok)
            continue
        i = rng.randrange(1, len(core) - 1)
        op = rng.choice(["swap", "drop", "dup"])
        bad = core[:i] + core[i + 1] + core[i] + core[i + 2:] if op == "swap" else (
            core[:i] + core[i + 1:] if op == "drop" else core[:i] + core[i] + core[i:])
        out.append(tok.replace(core, bad, 1))
    return " ".join(out)


def make_ctx(rng: random.Random, st_key: str, emp: Emp, location: str | None = None) -> dict:
    code = LOCATIONS.get(location or emp.location, ("HQ", 0))[0]
    st = T.SUBTYPES.get(st_key, {})
    if st_key == "sw_crash" or st_key.startswith("sw_license"):
        app = rng.choice(T.APPS_CRASH if st_key == "sw_crash" else ["Microsoft Office", "Adobe Acrobat", "Visio"])
    elif st_key == "sw_install_request":
        app = rng.choice(T.APPS_INSTALL)
    elif st_key.startswith("ap_"):
        app = rng.choice(T.APPS_ACCESS + ["Windows"])
    else:
        app = rng.choice(T.APPS_CRASH)
    errs = st.get("errs") or []
    return {
        "device": f"{rng.choice(['LT', 'DT'])}-{code}-{rng.randint(1000, 9999)}",
        "printer": f"PRN-{code}-{rng.randint(1, 5)}F-{rng.randint(1, 12):02d}",
        "app": app, "err": rng.choice(errs) if errs else "an error", "site": rng.choice(T.SITES),
        "name": emp.name, "title": emp.title,
    }


def signature(rng: random.Random, emp: Emp) -> str:
    sig = fill(rng.choice(T.SIGNATURES), {"name": emp.name, "first": emp.first, "dept": emp.dept, "location": emp.location,
                                           "phone": emp.phone, "emp": emp.emp_id, "title": emp.title, "ext": emp.ext})
    if rng.random() < 0.35:
        sig = (sig + "\n\n" if sig else "") + rng.choice(T.DISCLAIMERS)
    return sig


def wrap(rng: random.Random, emp: Emp, core: str, inline_pii: bool = True) -> str:
    """greeting + core + (maybe inline PII) + closer + signature/disclaimer."""
    parts = [rng.choice(T.GREETINGS), core]
    if inline_pii and rng.random() < 0.14:
        parts.append(rng.choice([f"you can reach me on {emp.phone}", f"my employee id is {emp.emp_id}",
                                 f"alt email {emp.first.lower()}{rng.randint(10, 99)}@gmail.com", f"call me at {emp.phone}"]))
    parts.append(rng.choice(T.CLOSERS))
    body = "\n".join(p for p in parts[:1]) + ("\n" if parts[0] else "") + ". ".join(p for p in parts[1:] if p)
    sig = signature(rng, emp)
    return body + ("\n\n" + sig if sig else "")


def draw_levels(rng: random.Random, st: dict) -> tuple[int, int]:
    """(scope level 3=single/2=team/1=wide, urgency level 1=high..3=low)."""
    sr = st["type"] == "Service Request"
    scope = rng.choices([3, 2, 1], weights=[0.92, 0.08, 0.0] if sr else [0.76, 0.17, 0.07])[0]
    bias = st.get("urgency")
    uw = [0.40, 0.40, 0.20] if bias == "high" else ([0.06, 0.29, 0.65] if bias == "low" else ([0.15, 0.35, 0.50] if sr else [0.38, 0.45, 0.17]))
    return scope, rng.choices([1, 2, 3], weights=uw)[0]


def prio(scope: int, urgency: int, critical: bool) -> str:
    impact = max(1, scope - 1) if critical else scope
    return PRIORITY_MATRIX[(impact, urgency)]


def compose_core(rng, st_key, ctx, scope, urg, messy, vague) -> tuple[str, str]:
    st = T.SUBTYPES[st_key]
    subject = rng.choice(T.VAGUE_SUBJECTS) if vague else rng.choice(st["subjects"])
    text = rng.choice(T.VAGUE_BODIES) if vague else rng.choice(st["bodies"])
    text = apply_typos(rng, text, 0.14 if messy else 0.05)
    parts = [text]
    if not vague and rng.random() < 0.4:
        parts.append(rng.choice(T.DETAIL_PHRASES))
    if (sc := rng.choice(T.SCOPE_PHRASES[scope])):
        parts.append(sc)
    if rng.random() > 0.12:  # 12% never state urgency -> pipeline must default
        parts.append(rng.choice(T.URGENCY_PHRASES[urg]))
    core = ". ".join(parts)
    subject, core = fill(subject, ctx), fill(core, ctx)
    r = rng.random()
    if r < 0.10:
        subject = rng.choice(["URGENT!!! ", "urgent!! ", "ASAP - ", "!!! "]) + subject
    elif r < 0.13:
        core = core.upper()
    elif r < 0.17:
        core += rng.choice([" pls fix asap!!!", " urgent!!!", " PLEASE HELP!!", " ???"])
    if rng.random() < 0.04:
        subject = rng.choice(["RE: ", "FW: "]) + subject
    return subject, core


def base_row(emp_email: str, dept, loc, created, subject, body, st_key, category, ttype, priority, scenario="normal") -> dict:
    return dict(created_at=created, requester_email=emp_email, department=dept, location=loc, subject=subject[:300], body=body,
                true_category=category, true_priority=priority, true_ticket_type=ttype, subtype=st_key, scenario=scenario,
                is_malicious=False, attack_type="", dup_of="", resolved_at=None, resolution_notes="", assigned_team="",
                initial_team="", reassignment_count=0, resolution_channel="agent", status="Open")


def lifecycle(rng: random.Random, row: dict, self_service_p: float = 0.0, vague: bool = False, resolved_at=None, notes_pool=None) -> None:
    """Fill resolver team, baseline (human) routing, reassignments, resolution time and status."""
    cat, prio_ = row["true_category"], row["true_priority"]
    team = CATEGORY_TEAM[cat]
    row["assigned_team"] = team
    if rng.random() < (0.45 if vague else 0.22):
        row["initial_team"] = rng.choice(MISROUTE[cat])
        row["reassignment_count"] = 1 if rng.random() < 0.7 else 2
    else:
        row["initial_team"] = team
        row["reassignment_count"] = 1 if rng.random() < 0.06 else 0
    notes = rng.choice(notes_pool) if notes_pool else "Resolved."
    if resolved_at is None:
        if rng.random() < self_service_p:
            row["resolution_channel"], row["reassignment_count"], row["initial_team"] = "self_service_kb", 0, team
            hours, notes = rng.uniform(0.1, 2.0), "Resolved by the user via self-service KB article; no agent action."
        else:
            hours = MEDIAN_H[prio_] * rng.lognormvariate(0, 0.6) + 5.0 * row["reassignment_count"]
        resolved_at = row["created_at"] + timedelta(hours=hours)
    if resolved_at <= END and rng.random() > 0.015:
        row.update(resolved_at=resolved_at, status="Resolved", resolution_notes=notes)
    else:
        row.update(resolved_at=None, status=rng.choice(["Open", "In Progress", "In Progress"]), resolution_notes="")


# ----------------------------------------------------------------------------- generation
def generate(seed: int = SEED, n_total: int = N_TOTAL) -> pd.DataFrame:
    rng = random.Random(seed)
    emps = make_employees(rng)
    internal = [e for e in emps if e not in emps[:6]]
    by_loc: dict[str, list[Emp]] = {}
    for e in internal:
        by_loc.setdefault(e.location, []).append(e)
    sampler = Sampler()
    rows: list[dict] = []
    n_special = N_OUTAGE + N_DUP + N_SE + N_INJ + N_DEC_EXEC + N_DEC_IGN

    def build(emp: Emp, st_key: str, created: datetime, scenario="normal", location=None, force_clean=False) -> dict:
        st = T.SUBTYPES[st_key]
        vague = (not force_clean) and rng.random() < 0.08
        scope, urg = draw_levels(rng, st)
        ctx = make_ctx(rng, st_key, emp, location or emp.location)
        subject, core = compose_core(rng, st_key, ctx, scope, urg, rng.random() < 0.3, vague)
        row = base_row(emp.email, emp.dept, location or emp.location, created, subject, wrap(rng, emp, core), st_key,
                       st["category"], st["type"], prio(scope, urg, st.get("critical", False)), scenario)
        row["_core"], row["_vague"] = core, vague
        return row

    # --- normal traffic
    for _ in range(n_total - n_special):
        cat = weighted(rng, CAT_WEIGHTS)
        keys = [k for k, v in T.SUBTYPES.items() if v["category"] == cat]
        st_key = rng.choices(keys, weights=[T.SUBTYPES[k]["weight"] for k in keys])[0]
        if cat == "Printer":  # concentrate printer problems in one office
            loc = PRINTER_HOTSPOT[0] if rng.random() < PRINTER_HOTSPOT[1] else rng.choice(
                [l for l in by_loc if l != PRINTER_HOTSPOT[0]])
            emp = rng.choice(by_loc[loc])
        else:
            emp = rng.choice(internal)
        row = build(emp, st_key, sampler.sample(rng, vpn=(st_key == "nw_vpn")))
        lifecycle(rng, row, T.SUBTYPES[st_key]["self_service"], row["_vague"], notes_pool=T.SUBTYPES[st_key]["notes"])
        if rng.random() < 0.05:  # label noise: a human filed it under the wrong category
            row["true_category"] = rng.choice([c for c in CATEGORIES if c != row["true_category"]])
            row["assigned_team"] = CATEGORY_TEAM[row["true_category"]]
        rows.append(row)

    # --- email outage: 40 near-identical tickets from 40 distinct users inside 14 minutes
    offsets = sorted(rng.uniform(0, 14 * 60) for _ in range(N_OUTAGE))
    t_str = OUTAGE_START.strftime("%I:%M %p").lstrip("0")
    resolved = OUTAGE_START + timedelta(minutes=150 + rng.randint(0, 25))
    for emp, off in zip(rng.sample(internal, N_OUTAGE), offsets):
        created = OUTAGE_START + timedelta(seconds=off)
        core = apply_typos(rng, fill(rng.choice(T.OUTAGE_BODIES), {"t": t_str}), 0.04)
        row = base_row(emp.email, emp.dept, emp.location, created, rng.choice(T.OUTAGE_SUBJECTS), wrap(rng, emp, core, False),
                       "em_send_receive", "Email", "Incident", "P1", "outage")
        lifecycle(rng, row, resolved_at=resolved,
                  notes_pool=["Exchange Online mail-flow connector fault at provider; restored via failover. Linked to major incident."])
        row["reassignment_count"] = 0 if row["reassignment_count"] == 0 else 1
        rows.append(row)

    # --- same-user duplicates (follow-ups)
    pool = [r for r in rows if r["scenario"] == "normal" and not r["_vague"] and r["created_at"] < END - timedelta(days=2)]
    for orig in rng.sample(pool, N_DUP):
        emp = next(e for e in internal if e.email == orig["requester_email"])
        lead = rng.choice(["still facing this issue, any update?", "following up on my earlier ticket, nobody has responded",
                           "raising again as this is not resolved", "second request, please check"])
        created = orig["created_at"] + timedelta(hours=rng.uniform(0.5, 20))
        row = base_row(emp.email, emp.dept, orig["location"], created, orig["subject"], wrap(rng, emp, f"{lead} {orig['_core']}", False),
                       orig["subtype"], orig["true_category"], orig["true_ticket_type"], orig["true_priority"], "duplicate")
        row.update(assigned_team=orig["assigned_team"], initial_team=orig["initial_team"],
                   resolved_at=orig["resolved_at"], status=orig["status"], resolution_notes="Merged with original ticket.",
                   resolution_channel=orig["resolution_channel"])
        row["_dup_ref"] = orig
        rows.append(row)

    # --- social engineering (6 lookalike, 3 free-mail, 3 internal sender)
    senders = ["lookalike"] * 6 + ["freemail"] * 3 + ["internal"] * 3
    for i, kind in enumerate(senders):
        ex = EXECS[i % len(EXECS)]
        local = f"{ex[0]}.{ex[1]}".lower()
        if kind == "lookalike":
            email, dept, loc = f"{local}@{LOOKALIKES[i % len(LOOKALIKES)]}", "Unknown", "Unknown"
        elif kind == "freemail":
            email, dept, loc = f"{local}{rng.randint(1, 99)}@{rng.choice(FREEMAIL)}", "Unknown", "Unknown"
        else:
            e = rng.choice(internal)
            email, dept, loc = e.email, e.dept, e.location
        created = sampler.sample(rng)
        row = base_row(email, dept, loc, created, rng.choice(T.SE_SUBJECTS), T.SE_TEXTS[i % len(T.SE_TEXTS)] + f"\n\n{ex[0]} {ex[1]}\n{ex[2]}",
                       "attack_se", "Access/Password", "Service Request", "P3", f"attack_se_{kind}")
        row.update(is_malicious=True, attack_type="social_engineering", assigned_team=CATEGORY_TEAM["Access/Password"],
                   initial_team=CATEGORY_TEAM["Access/Password"], resolved_at=created + timedelta(hours=rng.uniform(1, 6)),
                   status="Resolved", resolution_notes="Closed by security: request failed identity verification; no action taken.")
        rows.append(row)

    # --- prompt injection riding on a benign problem
    for i in range(N_INJ):
        emp = rng.choice(internal)
        key = T.INJECTION_CORES[i % len(T.INJECTION_CORES)]
        row = build(emp, key, sampler.sample(rng), "attack_injection", force_clean=True)
        row["body"] = row["body"].replace(row["_core"], row["_core"] + ". " + T.INJECTION_SUFFIXES[i % len(T.INJECTION_SUFFIXES)])
        row.update(is_malicious=True, attack_type="prompt_injection")
        lifecycle(rng, row, 0.0, notes_pool=["Closed by security: ticket contained embedded instructions; real issue handled separately."])
        rows.append(row)

    # --- decoys: legitimate but look suspicious
    for i, (key, text) in enumerate(T.DECOY_EXEC):
        ex = emps[i % len(EXECS)]
        st = T.SUBTYPES[key]
        ctx = make_ctx(rng, key, ex)
        row = base_row(ex.email, ex.dept, ex.location, sampler.sample(rng), rng.choice(st["subjects"]),
                       wrap(rng, ex, fill(text, ctx), False), key, st["category"], st["type"], "P2", "decoy_exec")
        lifecycle(rng, row, 0.0, notes_pool=st["notes"])
        rows.append(row)
    for key, text in T.DECOY_IGNORE:
        emp = rng.choice(internal)
        st = T.SUBTYPES[key]
        row = base_row(emp.email, emp.dept, emp.location, sampler.sample(rng), rng.choice(st["subjects"]),
                       wrap(rng, emp, fill(text, make_ctx(rng, key, emp)), False), key, st["category"], st["type"], "P3", "decoy_ignore")
        lifecycle(rng, row, 0.0, notes_pool=st["notes"])
        rows.append(row)

    # --- ids in chronological order; resolve duplicate pointers
    rows.sort(key=lambda r: r["created_at"])
    for n, r in enumerate(rows, 1):
        r["ticket_id"] = f"TCK-{n:06d}"
    for r in rows:
        r["dup_of"] = r["_dup_ref"]["ticket_id"] if "_dup_ref" in r else ""
    df = pd.DataFrame(rows)
    cols = ["ticket_id", "created_at", "requester_email", "department", "location", "subject", "body", "true_category",
            "true_priority", "true_ticket_type", "resolved_at", "resolution_notes", "assigned_team", "initial_team",
            "reassignment_count", "resolution_channel", "status", "subtype", "scenario", "is_malicious", "attack_type", "dup_of"]
    return df[cols]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "raw" / "tickets.csv"))
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--n", type=int, default=N_TOTAL)
    a = ap.parse_args()
    df = generate(a.seed, a.n)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    print(f"wrote {len(df)} tickets -> {a.out}")
    print(df["true_category"].value_counts().to_string())


if __name__ == "__main__":
    main()
