"""Simulate a live ticket stream against the running API.

    python -m scripts.simulate_stream --n 40 --delay 0.5
    python -m scripts.simulate_stream --burst-outage        # replays an email outage -> live major incident
    python -m scripts.simulate_stream --attacks             # include social-engineering / injection tickets
    python -m scripts.simulate_stream --email-webhook       # send via /webhook/email instead of /tickets

Tickets come from a fresh seed of the generator (not the training history).
"""
from __future__ import annotations

import argparse
import random
import time

import httpx
import pandas as pd

from app.config import get_settings
from data.generator.generate_tickets import generate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=777)
    ap.add_argument("--burst-outage", action="store_true")
    ap.add_argument("--attacks", action="store_true")
    ap.add_argument("--email-webhook", action="store_true")
    ap.add_argument("--url", default=get_settings().api_url)
    a = ap.parse_args()

    df = generate(seed=a.seed, n_total=1500)
    pool = df[df.scenario.isin(["normal", "decoy_exec", "decoy_ignore"])]
    picks = [pool.sample(a.n, random_state=a.seed)]
    if a.attacks:
        picks.append(df[df.is_malicious].sample(6, random_state=a.seed))
    rows = pd.concat(picks).sample(frac=1, random_state=a.seed)
    if a.burst_outage:  # 25 outage reports from distinct users, back-to-back -> live major-incident detection
        rows = pd.concat([rows, df[df.scenario == "outage"].head(25)])

    with httpx.Client(base_url=a.url, timeout=30) as c:
        for r in rows.itertuples():
            if a.email_webhook:
                resp = c.post("/webhook/email", json={"from": f"{r.requester_email}", "to": "helpdesk@acmecorp.com",
                                                         "subject": r.subject, "text": r.body, "message_id": f"<{random.getrandbits(48):x}@sim>"})
            else:
                resp = c.post("/tickets", json={"requester_email": r.requester_email, "subject": r.subject, "body": r.body})
            if resp.status_code >= 300:
                print("ERR", resp.status_code, resp.text[:120])
                continue
            j = resp.json()
            print(f"{j['ticket_id']} {j['priority']} {str(j['category']):16s} conf={j['confidence']:.2f} -> {j['routed_queue']:20s}"
                  f"{' [' + j['security_flag'] + ']' if j['security_flag'] else ''}{' INCIDENT ' + j['incident_id'] if j['incident_id'] else ''}"
                  f"{' DUP of ' + j['duplicate_of'] if j['duplicate_of'] else ''}")
            time.sleep(0 if r.scenario == "outage" else a.delay)


if __name__ == "__main__":
    main()
