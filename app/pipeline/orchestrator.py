"""Pipeline orchestrator: clean -> security screen -> classify -> entities -> priority -> route -> KB -> action policy.

Every step writes a timestamped audit_log row (decision + reason); routing writes routing_log.
Intelligence (duplicates, then major incidents) runs afterwards via `run_intelligence`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.audit import log_decision
from app.config import get_settings
from app.constants import QUEUE_NEEDS_REVIEW, QUEUE_SECURITY
from app.models import Classification, Entity, RoutingLog, Ticket
from app.pipeline import entities as ent_mod
from app.pipeline import kb, llm_classifier, priority
from app.pipeline.classifier import Prediction, get_classifier
from app.pipeline.cleaner import clean_ticket
from app.pipeline.router import route
from app.security.action_policy import plan_actions
from app.security.injection import detect_injection, strip_injection
from app.security.sender_domain import classify_sender
from app.security.social_engineering import detect_social_engineering


@dataclass
class Outcome:
    category: str
    confidence: float
    queue: str
    priority: str
    security_flag: str | None


def process_ticket(s: Session, t: Ticket, *, live: bool = True, now: datetime | None = None,
                   pred: Prediction | None = None, llm_client=None) -> Outcome:
    cfg = get_settings()
    ts = now or datetime.utcnow()
    tid = t.ticket_id

    def tick() -> datetime:  # strictly increasing timestamps so the audit trail replays in order
        nonlocal ts
        ts += timedelta(milliseconds=50)
        return ts

    # 1. Clean + PII redaction (before ANYTHING else sees the text)
    cr = clean_ticket(t.subject, t.raw_body)
    t.clean_text = cr.text
    t.sender_domain = t.requester_email.rsplit("@", 1)[-1].lower()
    log_decision(s, tid, "clean", "pii_redacted", f"redactions={cr.redactions or 'none'}; signature_stripped={cr.signature_stripped}", ts=tick())

    # 2. Security screen: ticket text is untrusted data
    inj = detect_injection(cr.text)
    se = detect_social_engineering(cr.text, t.requester_email, cfg.corporate_domain)
    flag = "prompt_injection" if inj.flagged else ("social_engineering" if se.flagged else None)
    t.security_flag, t.security_score = flag, max(inj.score, se.score)
    if inj.flagged:
        log_decision(s, tid, "security", "prompt_injection_blocked", f"signals={inj.matches}; score={inj.score}; injected text removed before classification", ts=tick())
    if se.flagged:
        log_decision(s, tid, "security", "social_engineering_flagged",
                     f"signals={se.signals}; score={se.score}; sender={classify_sender(t.requester_email, cfg.corporate_domain)}", ts=tick())
    if not flag:
        log_decision(s, tid, "security", "screen_clear", f"injection={inj.score}, social_eng={se.score}", ts=tick())
    work = strip_injection(cr.text) if inj.flagged else cr.text  # classify the real issue, not the payload

    # 3. Classify (sklearn default; optional LLM on clean_text only, validated, with fallback)
    pred = pred or get_classifier().predict(work)
    category, conf, ttype, method = pred.category, pred.confidence, pred.ticket_type, "sklearn"
    version = get_classifier().version
    if cfg.use_llm:
        if inj.flagged:
            log_decision(s, tid, "classify", "llm_skipped", "injection detected: untrusted text never reaches the LLM", ts=tick())
        elif llm_classifier.enabled() or llm_client is not None:
            try:
                out = llm_classifier.classify(work, client=llm_client)  # clean_text only, never raw_body
                if out.category == category:
                    conf, ttype, method = max(conf, 0.90), out.ticket_type, "llm"
                    log_decision(s, tid, "classify", "llm_agrees", f"llm={out.category}, advisory priority={out.priority} ignored", actor="llm", ts=tick())
                else:
                    conf, method = min(conf, 0.50), "llm"
                    log_decision(s, tid, "classify", "llm_disagrees", f"llm={out.category} vs sklearn={category}: confidence capped -> human review", actor="llm", ts=tick())
            except llm_classifier.LLMRejected as e:
                method = "llm_fallback"
                log_decision(s, tid, "classify", "llm_rejected_fallback_sklearn", str(e), actor="llm", ts=tick())
    t.category, t.ticket_type, t.confidence = category, ttype, conf
    s.add(Classification(ticket_pk=t.id, category=category, ticket_type=ttype, confidence=conf, type_confidence=pred.type_confidence,
                         method=method, model_version=version, created_at=ts))
    log_decision(s, tid, "classify", f"{category} / {ttype}", f"confidence={conf:.3f}; method={method}; model={version}", ts=tick())

    # 4. Entities
    ents = ent_mod.extract(work)
    for e in ents:
        s.add(Entity(ticket_pk=t.id, entity_type=e.type, value=e.value[:200]))
    log_decision(s, tid, "entities", f"{len(ents)} entities", ", ".join(f"{e.type}:{e.value}" for e in ents[:8]), ts=tick())

    # 5. Priority (ITIL impact x urgency; text can never set priority directly)
    pr = priority.compute(work, ttype, capped=bool(flag))
    t.priority = t.initial_priority = pr.priority
    t.impact, t.urgency = pr.impact, pr.urgency
    log_decision(s, tid, "priority", pr.priority, "; ".join(pr.reasons), ts=tick())

    # 6. Route (security > low confidence > auto-assign)
    d = route(category, conf, cfg.threshold, flag)
    t.routed_queue = d.queue
    s.add(RoutingLog(ticket_pk=t.id, ts=tick(), step="route", from_queue="Intake", to_queue=d.queue, confidence=conf, reason=d.reason))
    log_decision(s, tid, "route", d.queue, d.reason, ts=tick())

    # 7. Suggest fix (SAFE action)
    hit = None if flag else kb.suggest(work, category)
    t.kb_article_id, t.kb_score = (hit.id, hit.score) if hit else (None, None)
    log_decision(s, tid, "kb", hit.id if hit else "no_match", f"{hit.title} (score {hit.score:.2f}) {hit.url}" if hit else "no article above similarity floor", ts=tick())

    # 8. Automation safety tier
    plan = plan_actions(work, category, ttype, hit is not None, flag)
    t.action_tier, t.action_status = plan.tier, plan.status
    log_decision(s, tid, "action_policy", f"{plan.tier}: {plan.status}",
                 f"safe={plan.safe_actions}; needs_approval={plan.approval_actions}; {plan.note}".strip("; "), ts=tick())

    t.processed_at = ts
    if live:
        t.status = {QUEUE_NEEDS_REVIEW: "Needs Review", QUEUE_SECURITY: "Security Review"}.get(d.queue, "Assigned")
    return Outcome(category, conf, d.queue, pr.priority, flag)


def run_intelligence(s: Session, t: Ticket, ts: datetime | None = None) -> None:
    """Duplicates FIRST (so repeat tickets from one user cannot inflate incident counts), then major incidents."""
    from app.intelligence.duplicates import check_duplicate
    from app.intelligence.incidents import check_incident
    if check_duplicate(s, t, ts) is None:
        check_incident(s, t, ts)
