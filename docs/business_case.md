# TriageIQ - business case

> All volumes below come from a **synthetic** 90-day helpdesk (3,000 tickets) generated for this portfolio project. Rates are measured on that data; cost inputs are **assumptions** you can change in the dashboard (Business impact page).

## 1. The problem in business terms
L1 helpdesks receive many repetitive, poorly described tickets. In the baseline history:

* **24% of tickets were first sent to the wrong team** and needed a hand-off (avg 0.30 reassignments per ticket).
* Misrouted tickets **breach SLA 33% of the time vs 16%** when routed correctly - misrouting is a direct SLA cost, not just an annoyance.
* **18% of volume is password/unlock/access requests** - high-volume, low-complexity, and a security-sensitive workflow.
* **First-contact resolution is 75%**; overall SLA breach rate is **20%** (P1 42%, P2 46%, P3 26%, P4 10% - calendar hours; targets P1 4h, P2 8h, P3 24h, P4 72h).
* One mail outage generated **40 tickets from 40 users in 14 minutes**, each handled as a separate ticket.
* Nobody could see *why* tickets recur (Monday-morning VPN peaks; 51% of printer tickets from one office).

## 2. What TriageIQ changes
| Capability | Effect |
|---|---|
| Classify (Incident vs Service Request, category) + ITIL priority + confidence-gated routing | Routes automatically when confident; sends the rest to a human "Needs Review" queue |
| KB suggestion on every ticket | Shorter handling and more self-service |
| Duplicate merge + major-incident detection | One parent P1 instead of dozens of separate tickets |
| Root-cause insights | Fixes recurring causes, not just tickets |
| Security guardrails | No account/access action is ever auto-executed; suspicious tickets quarantined |

## 3. Measured results (held-out tickets the model never trained on, n = 582)
| Metric | Baseline (manual L1) | TriageIQ |
|---|---|---|
| Misrouted tickets | 25.1% of all tickets (146) | 4.9% of the tickets it auto-routes (26 of 535) |
| Auto-routed / human review | 0% / 100% manual triage | 91.9% / 8.1% |
| **Misroutes avoided** | | **120 per 582 tickets (~21% of volume)** |
| **Reassignments saved (est.)** | | **~127 per 582 tickets (0.22 per ticket)** |
| Category accuracy | | 88.8% (auto-routed subset 95.1%) |

Caveats: the synthetic history contains ~5% deliberate label noise, so some "pipeline misroutes" are mislabelled ground truth (we count them against the system). The hand-written out-of-template set currently has only 5 rows (80% accuracy) - far too small to be evidence; real-world accuracy is unknown until it is filled with ~50 real tickets.

## 4. Estimated savings (default assumptions)
Assumptions (all adjustable on the dashboard): **1,011 tickets/month** (the dataset's rate), **20 min** average handling, **25%** of handling is manual triage, **₹450/hour** agent cost, **20 min** lost per reassignment, **3 min** human review per Needs-Review ticket, **3%** of volume deflected extra via KB suggestions.

| Component | Hours / month |
|---|---|
| Automatic triage and routing (91.9% of tickets x 5 min) | 77.4 |
| Fewer misroutes / reassignments | 73.3 |
| KB deflection uplift (assumption) | 10.1 |
| Duplicates merged (1.0% of tickets x 50% of handling) | 1.7 |
| Incident children handled once | 2.0 |
| LESS: human review of low-confidence tickets | -4.1 |
| **Total** | **~160 h/month** |

**≈ ₹72,000 per month (≈ ₹8.7 lakh per year), about 1.0 FTE of capacity freed.** This is time freed for higher-value work, not headcount removed; the figures scale linearly with the assumptions above.

## 5. Risks and controls
* **Wrong auto-route:** confidence threshold chosen from a coverage-vs-accuracy curve (0.55: 91.9% coverage at 95.1% accuracy); low-confidence tickets go to humans; agents can submit corrections that feed `scripts/retrain_with_feedback.py` (only promoted if held-out accuracy does not drop).
* **Social engineering / prompt injection:** flagged tickets are quarantined, cannot escalate priority, and no sensitive action is executed automatically (see `security_design.md`).
* **Synthetic-data optimism:** replace with a real ticket export (PII-redacted) before drawing conclusions.
