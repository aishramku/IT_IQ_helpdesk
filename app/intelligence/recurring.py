"""Recurring-issue analysis -> plain-English root-cause recommendations.

Operates on a tickets DataFrame (see app.analytics.tickets_df) so it is trivially testable.
Each insight = what we saw (with evidence) + what to check/do about it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

DOW = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass
class Insight:
    title: str
    finding: str
    recommendation: str
    severity: str = "medium"  # high | medium | low
    evidence: dict = field(default_factory=dict)


def _spikes(df: pd.DataFrame, label: str, mask: pd.Series, advice: str, min_n: int = 12, factor: float = 2.5) -> list[Insight]:
    """Weekday x hour spikes: hours where one weekday runs >= `factor`x the same hour on the other weekdays."""
    d = df[mask & (df.dow < 5)]
    if len(d) < min_n:
        return []
    n_days = df[df.dow < 5].groupby("dow").date.nunique()
    cell = d.groupby(["dow", "hour"]).size()
    rate = {k: c / n_days.get(k[0], 1) for k, c in cell.items()}  # tickets per day in that weekday-hour
    hot = []
    for (dw, h), r in rate.items():
        base = sum(rate.get((d2, h), 0.0) for d2 in range(5) if d2 != dw) / 4  # zeros count: "no tickets" is a baseline too
        if cell[(dw, h)] >= 8 and (base == 0 or r / base >= factor):
            hot.append((dw, h, r, base, int(cell[(dw, h)])))
    if not hot:
        return []
    by_day: dict[int, list] = {}
    for x in hot:
        by_day.setdefault(x[0], []).append(x)
    dw, items = max(by_day.items(), key=lambda kv: sum(i[4] for i in kv[1]))
    # keep only the contiguous run around the peak hour (neighbours with >= half the peak volume)
    by_hour = {i[1]: i for i in items}
    peak = max(items, key=lambda i: i[4])
    lo = hi = peak[1]
    while lo - 1 in by_hour and by_hour[lo - 1][4] >= 0.5 * peak[4]:
        lo -= 1
    while hi + 1 in by_hour and by_hour[hi + 1][4] >= 0.5 * peak[4]:
        hi += 1
    items = [by_hour[h] for h in range(lo, hi + 1)]
    h0, h1 = lo, hi + 1
    r, base = sum(i[2] for i in items), sum(i[3] for i in items)
    ratio = min(r / base, 99.0) if base else 99.0
    return [Insight(f"{label} spike on {DOW[dw]} {h0:02d}:00-{h1:02d}:00",
                    f"{label} tickets run at {ratio:.1f}x the usual rate on {DOW[dw]} {h0:02d}:00-{h1:02d}:00 "
                    f"({r:.1f}/day vs {base:.1f}/day at the same hours on other weekdays).", advice, "high",
                    {"day": DOW[dw], "hours": f"{h0:02d}-{h1:02d}", "ratio": round(ratio, 1), "tickets": sum(i[4] for i in items)})]


def analyze(df: pd.DataFrame, inc: pd.DataFrame | None = None) -> list[Insight]:
    df = df[~df.is_malicious.astype(bool) & df.duplicate_of.isna()].copy()
    out: list[Insight] = []
    # a one-off major incident is reported separately; keeping its children would fake a recurring spike
    spk = df[df["incident_id"].isna()] if "incident_id" in df else df

    vpn = spk.clean_text.fillna("").str.contains(r"\bvpn\b|globalprotect", case=False)
    out += _spikes(spk, "VPN", vpn, "Check concurrent VPN licence/session limits and gateway capacity before the Monday-morning peak; "
                                     "consider adding gateways or staggering remote-work start times.")
    for cat, advice in (("Email", "Review mail-flow capacity and any scheduled jobs in this window."),
                        ("Access/Password", "Promote self-service password reset; expired-password cycles often align after weekends.")):
        out += _spikes(spk, cat, spk.category == cat, advice, min_n=40, factor=3.0)

    # location concentration vs the company-wide ticket share
    share_all = df.location.value_counts(normalize=True)
    for cat in df.category.dropna().unique():
        sub = df[df.category == cat]
        if len(sub) < 40:
            continue
        top = sub.location.value_counts(normalize=True)
        loc, s = top.index[0], float(top.iloc[0])
        exp = float(share_all.get(loc, 0))
        if s >= 1.6 * exp and s >= 0.35:
            tail = ("Inspect the devices/print server at that site and check for ageing hardware or a misconfigured print queue." if cat == "Printer"
                    else "Investigate site-specific infrastructure (switches, access points, local config).")
            out.append(Insight(f"{cat} issues concentrated in {loc}", f"{s:.0%} of {cat} tickets come from {loc}, which generates only {exp:.0%} of all tickets "
                               f"({s / exp:.1f}x over-represented).", tail, "high", {"location": loc, "share": round(s, 3), "expected": round(exp, 3)}))

    # top recurring problems (by KB topic) and self-service opportunity
    kbc = df.kb_article_id.value_counts()
    if len(kbc):
        top = kbc.head(5)
        out.append(Insight("Top recurring problems", "; ".join(f"{k}: {v} tickets ({v / len(df):.0%})" for k, v in top.items()),
                           "Fix the top root causes proactively and promote self-service articles for the most frequent items.", "medium",
                           {k: int(v) for k, v in top.items()}))
    pw = df[(df.category == "Access/Password") & (df.ticket_type == "Service Request")]
    if len(pw) / max(len(df), 1) > 0.10:
        out.append(Insight("Password/account requests are a top volume driver",
                           f"{len(pw)} password/unlock/access requests = {len(pw) / len(df):.0%} of all tickets.",
                           "Roll out self-service password reset + account unlock with MFA. This removes most of them from agent queues "
                           "without weakening identity verification.", "high", {"tickets": len(pw)}))

    # repeat requesters
    rep = df.requester_email.value_counts()
    cut = max(8.0, rep.mean() + 2.5 * rep.std())  # statistical outliers, not just "above average"
    heavy = rep[rep >= cut]
    if len(heavy):
        out.append(Insight("Repeat requesters", f"{len(heavy)} users raised >= {cut:.0f} tickets in the period (max {int(rep.iloc[0])}; average {rep.mean():.1f}).",
                           "Review their devices/profiles for chronic faults (refresh or re-image) and offer proactive training.", "low",
                           {"users": len(heavy)}))

    # major incidents
    if inc is not None and len(inc):
        for _, r in inc.iterrows():
            dur = (r.resolved_at - r.window_start).total_seconds() / 3600 if pd.notna(r.resolved_at) else None
            out.append(Insight(f"Major incident {r.incident_id}: {r.category}",
                               f"{int(r.ticket_count)} tickets from {int(r.distinct_requesters)} requesters between {r.window_start:%H:%M} and {r.window_end:%H:%M} on {r.window_start:%d %b}."
                               + (f" Resolved after {dur:.1f}h." if dur else ""),
                               "Add proactive monitoring/alerting on this service (e.g. mail-flow connector health) so detection happens before users call; "
                               "publish status updates to deflect duplicate tickets.", "high", {"incident": r.incident_id}))

    # baseline misrouting
    base = df[df.initial_team.notna() & df.assigned_team.notna()]
    mis = base[base.initial_team != base.assigned_team]
    if len(mis):
        pair = mis.groupby(["initial_team", "assigned_team"]).size().sort_values(ascending=False)
        (a, b), n = pair.index[0], int(pair.iloc[0])
        res = base.dropna(subset=["resolution_hours"])
        sla = res.priority.map({"P1": 4, "P2": 8, "P3": 24, "P4": 72})
        wrong = res.initial_team != res.assigned_team
        br_w, br_r = (res.resolution_hours > sla)[wrong].mean(), (res.resolution_hours > sla)[~wrong].mean()
        out.append(Insight("Most common manual misroute", f"{len(mis) / len(base):.0%} of tickets were first sent to the wrong team; the top pattern is "
                           f"{a} -> {b} ({n} tickets). Misrouted tickets breach SLA {br_w:.0%} of the time vs {br_r:.0%} when routed correctly.", "Automated category routing removes this handoff; review L1 routing guidance for this pair.",
                           "medium", {"misroute_rate": round(len(mis) / len(base), 3)}))
    return out
