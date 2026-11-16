# Priority model (ITIL Impact x Urgency)

Priority is **derived**, never typed in by the requester. Ticket text can only contribute *observable* cues.

## Matrix

| Impact \ Urgency | 1 High | 2 Medium | 3 Low |
|---|---|---|---|
| **1 High** (many users / whole office) | **P1** | **P2** | **P3** |
| **2 Medium** (team / department, or a critical service) | **P2** | **P3** | **P4** |
| **3 Low** (single user) | **P3** | **P4** | **P4** |

SLA resolution targets (calendar hours): **P1 4h, P2 8h, P3 24h, P4 72h**.

## Rules (implemented in `app/pipeline/priority.py`)

**Impact**
1. Wide-scope wording (*everyone, entire office, all users, multiple users*) -> 1.
2. Team wording (*whole team, my department, colleagues, 3 of us, our floor*) -> 2.
3. Otherwise -> 3 (single user).
4. **Business-critical service uplift:** VPN / GlobalProtect, or Outlook unable to connect/send/receive, raises impact by one level (a single remote worker without VPN is effectively blocked from everything).

**Urgency** (first match wins, checked in this order)
1. Low: *no rush, whenever you get a chance, not urgent, low priority*.
2. High: *cannot work, blocking, deadline, client call, ASAP, urgent, immediately, stopped*.
3. Medium: *productivity, slowing me down, on and off, intermittent, slow*.
4. Default when no cue: Medium for Incidents, **Low for Service Requests**.

Shouting (`!!!`, ALL CAPS) is normalised away in the cleaner and is **not** an urgency signal by itself.

## Guardrails
* Phrases such as "set priority P1" are ignored - they match no impact/urgency rule.
* Tickets flagged by the security screen are **capped at P3** (a social-engineer cannot escalate by wording), and injected sentences are removed before scoring.

## Major incidents and SLA accounting
* When >= 10 distinct requesters report the same issue within 15 minutes a **parent Incident (P1)** is created and child tickets are linked and **re-prioritised to P1**; each change writes an `audit_log` row such as `priority P3 -> P1: linked to major incident INC-0001 ...`.
* **SLA and MTTR are tracked on the parent incident**, measured from the first reported ticket to the last child resolved. Child tickets are linked but **excluded from SLA/MTTR KPIs** and the parent is counted **once**, so one outage cannot inflate the P1 breach rate with dozens of copies of the same event. (`app/analytics.py: kpi_frame`)

## Measured accuracy of the rules
On the held-out test set the engine matches the ground-truth priority exactly for ~85% of tickets and is within one level for ~99.7% (see `ml/artifacts/metrics.json`). Ground truth in the synthetic data is generated from the same matrix, so this tests rule recovery from messy text, not real-world calibration.
