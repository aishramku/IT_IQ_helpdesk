# Security design decisions

## Threat model
A helpdesk is a social-engineering target (password resets, access grants) and, once an LLM reads tickets, a prompt-injection target. The pipeline therefore treats **every ticket as untrusted input**.

## Controls

| Control | Where | Why |
|---|---|---|
| PII redaction (phones, employee IDs, emails) **before** classification, entity extraction, KB lookup, LLM and storage of `clean_text` | `pipeline/cleaner.py` | Minimises PII spread; only `tickets.raw_body` (restricted column) keeps the original |
| Automation tiers: SAFE (acknowledge, KB link) vs REQUIRES_APPROVAL (password reset, unlock, MFA reset, access grant, software install) | `security/action_policy.py` | The system **never executes** account or access actions; there is no code path that does. A reset only yields `verification_required` (simulated MFA / verified-channel callback) |
| Social-engineering score: urgency + authority claim + credential exfiltration + verification bypass + privileged request + **sender domain** (look-alike / free-mail) | `security/social_engineering.py`, `sender_domain.py` | A single signal (a genuinely urgent VP, a normal "reset my password") stays below the flag threshold; combinations flag |
| Prompt-injection score: override phrase + role change/tag injection + priority/privilege payload + schema leakage | `security/injection.py` | Requires >= 2 independent signals so "please ignore my previous ticket" is not flagged |
| Flagged tickets -> **Security Review** queue, never auto-assigned, actions blocked, priority capped at P3, injected text stripped before classification | `pipeline/orchestrator.py` | Quarantine without losing the real issue behind the payload |
| LLM path (optional, `USE_LLM=true`): receives **only `clean_text`**; wrapped as delimited untrusted data; skipped when injection detected; output must be one JSON object matching a strict schema (`extra="forbid"`, enum categories); any violation -> sklearn fallback; LLM priority is advisory only | `pipeline/llm_classifier.py` | An attacker-controlled string can influence at most a category label |
| Full audit trail: every automated decision with timestamp, actor and reason | `audit_log` | Accountability and post-incident review |
| Webhook shared secret (`WEBHOOK_TOKEN`, optional) + idempotency on `message_id` | `app/main.py` | Spoofed or replayed inbound email |

## Evaluation honesty
Detector precision/recall/false-positive rate are measured against hidden labels in the synthetic data, including 25 legitimate decoys (urgent real executives, "please ignore my previous ticket"). **The attack tickets and the detector rules share an author**, so the numbers are optimistic. Before relying on this, collect independently written attacks (red-team, real phishing reports) and re-measure.

## Known limitations
* Names in free text are not redacted (only phone, employee ID, email); adding spaCy PERSON redaction is straightforward.
* Pattern-based detectors can be evaded by paraphrase; they are a first layer. Ground-truth mitigation is the architectural rule that nothing risky is auto-executed regardless of what the detectors say.
* Sender address is taken from the payload; real deployments must verify SPF/DKIM/DMARC upstream.
