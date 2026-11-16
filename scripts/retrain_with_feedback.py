"""Retrain using agent corrections from the feedback table.

    python -m scripts.retrain_with_feedback

Corrections override labels for those tickets (added to the TRAIN side only). The new model replaces
the old one ONLY if held-out accuracy does not drop; the outcome is written to audit_log either way.
"""
from __future__ import annotations

import shutil

import numpy as np
import pandas as pd

from app.audit import log_decision
from app.db import session_scope
from app.models import Feedback, Ticket
from app.pipeline.cleaner import clean_ticket
from ml.train import MODEL_PATH, fit, split, build_frame


def _acc(bundle: dict, te: pd.DataFrame) -> float:
    X = bundle["vectorizer"].transform(te.text)
    return float(np.mean(bundle["cat_model"].predict(X) == te.category.values))


def main() -> dict:
    with session_scope() as s:
        fbs = s.query(Feedback).filter(Feedback.corrected_category.isnot(None)).all()
        rows = []
        for f in fbs:
            t = s.query(Ticket).filter(Ticket.ticket_id == f.ticket_id).one()
            rows.append({"ticket_id": f.ticket_id, "text": clean_ticket(t.subject, t.raw_body).text, "category": f.corrected_category,
                         "ticket_type": f.corrected_ticket_type or t.ticket_type or "Incident", "subtype": None, "scenario": "feedback",
                         "true_priority": f.corrected_priority or t.priority})
        n_fb = len(rows)
        tr, te = split(build_frame())
        if not rows:
            print("no category corrections in feedback table - nothing to retrain")
            return {"feedback_used": 0}
        extra = pd.DataFrame(rows)
        tr2 = pd.concat([tr[~tr.ticket_id.isin(extra.ticket_id)], extra], ignore_index=True)

        old = __import__("joblib").load(MODEL_PATH)
        new = fit(tr2)
        a_old, a_new = _acc(old, te), _acc(new, te)
        promoted = a_new >= a_old
        if promoted:
            shutil.copy(MODEL_PATH, MODEL_PATH.with_suffix(".prev.joblib"))
            __import__("joblib").dump(new, MODEL_PATH)
            for f in fbs:
                f.used_in_training = True
        log_decision(s, None, "retrain", "promoted" if promoted else "rejected",
                     f"feedback={n_fb}; held-out accuracy {a_old:.3f} -> {a_new:.3f}", actor="system",
                     details={"old": a_old, "new": a_new, "feedback": n_fb})
        print(f"feedback rows: {n_fb} | held-out accuracy {a_old:.3f} -> {a_new:.3f} | {'PROMOTED' if promoted else 'REJECTED (kept old model)'}")
        return {"feedback_used": n_fb, "old": a_old, "new": a_new, "promoted": promoted}


if __name__ == "__main__":
    main()
