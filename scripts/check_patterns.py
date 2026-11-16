"""Prove the injected patterns exist in the synthetic data.   python -m scripts.check_patterns"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from app.config import ROOT
from app.constants import CORPORATE_DOMAIN, SLA_HOURS


def main(csv: Path | None = None) -> None:
    df = pd.read_csv(csv or ROOT / "data" / "raw" / "tickets.csv", parse_dates=["created_at", "resolved_at"])
    df["dow"], df["hour"] = df.created_at.dt.dayofweek, df.created_at.dt.hour
    print(f"Tickets: {len(df)}   {df.created_at.min():%Y-%m-%d} -> {df.created_at.max():%Y-%m-%d}")
    print("\nCategory mix:\n" + df.true_category.value_counts(normalize=True).mul(100).round(1).to_string())
    print("\nTicket type split:\n" + df.true_ticket_type.value_counts().to_string())
    print("\nPriority mix:\n" + df.true_priority.value_counts().sort_index().to_string())

    # 1. VPN Monday 09-11 spike: per-day average in the 09-11 window, Monday vs other weekdays
    vpn = df[df.subtype == "nw_vpn"]
    win = vpn[vpn.hour.isin([9, 10]) & (vpn.dow < 5)]
    ndays = df.created_at.dt.normalize().nunique()
    mon_days = df[df.dow == 0].created_at.dt.normalize().nunique()
    oth_days = df[df.dow.isin([1, 2, 3, 4])].created_at.dt.normalize().nunique()
    mon = (win.dow == 0).sum() / mon_days
    oth = (win.dow != 0).sum() / oth_days
    print(f"\n[VPN] tickets: {len(vpn)} | Mon 09-11 avg/day: {mon:.2f} vs Tue-Fri 09-11 avg/day: {oth:.2f} -> {mon / oth:.1f}x spike")

    # 2. Email outage: largest 15-minute burst of Email incidents and distinct requesters
    em = df[df.true_category == "Email"].sort_values("created_at")
    best = (0, 0, None)
    for t in em.created_at:
        w = em[(em.created_at >= t) & (em.created_at < t + pd.Timedelta(minutes=15))]
        if len(w) > best[0]:
            best = (len(w), w.requester_email.nunique(), t)
    print(f"[OUTAGE] max Email tickets in any 15 min: {best[0]} from {best[1]} distinct requesters, starting {best[2]}")

    # 3. Printer concentration
    pr = df[df.true_category == "Printer"].location.value_counts(normalize=True).mul(100).round(1)
    print(f"[PRINTER] {len(df[df.true_category == 'Printer'])} tickets; top location {pr.index[0]} = {pr.iloc[0]}% (others <= {pr.iloc[1]}%)")

    # 4. Duplicates
    d = df[df.scenario == "duplicate"]
    print(f"[DUPLICATES] {len(d)} follow-up tickets; {df[df.dup_of.notna()].requester_email.nunique()} requesters involved")

    # 5. Security
    mal = df[df.is_malicious]
    print(f"[SECURITY] malicious: {len(mal)} -> {mal.attack_type.value_counts().to_dict()}")
    print("           by scenario:", df[df.scenario.str.startswith('attack')].scenario.value_counts().to_dict())
    off = ~df.requester_email.str.endswith("@" + CORPORATE_DOMAIN)
    print(f"           non-corporate sender domains: {int(off.sum())} -> {df[off].requester_email.str.split('@').str[1].value_counts().to_dict()}")
    print(f"           legitimate decoys: {df.scenario.str.startswith('decoy').sum()} ({df.scenario.value_counts().get('decoy_exec', 0)} urgent execs, "
          f"{df.scenario.value_counts().get('decoy_ignore', 0)} 'ignore previous' phrasing)")

    # 6. Baseline routing quality + SLA
    n = df[~df.is_malicious]
    mis = (n.initial_team != n.assigned_team)
    print(f"\n[BASELINE] human L1 misroute rate {mis.mean():.1%}; avg reassignments/ticket {n.reassignment_count.mean():.2f}; "
          f"self-service share {(n.resolution_channel == 'self_service_kb').mean():.1%}")
    r = n.dropna(subset=["resolved_at"]).copy()
    r["hours"] = (r.resolved_at - r.created_at).dt.total_seconds() / 3600
    r["breach"] = r.hours > r.true_priority.map(SLA_HOURS)
    print("[SLA] breach rate by priority (calendar hours): " + ", ".join(f"{p}={g.breach.mean():.0%}" for p, g in r.groupby("true_priority")))
    print(f"      resolved {len(r)}/{len(n)}; label-noise/vague text handled in Phase 2 metrics")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
