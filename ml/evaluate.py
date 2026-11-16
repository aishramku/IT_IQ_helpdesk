"""Evaluate the model + detectors and write ml/artifacts/metrics.json.

    python -m ml.evaluate

Outputs: classification report, confusion matrix PNG, coverage-vs-accuracy threshold curve
(0.50-0.95) with a data-driven default threshold, hand-written (out-of-template) accuracy,
KB retrieval hit-rate, priority-engine accuracy, and detector precision/recall/FPR.
"""
from __future__ import annotations

import json
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

from app.config import ARTIFACTS, ROOT, get_settings
from app.constants import CATEGORIES
from app.pipeline import entities, kb, priority
from app.pipeline.classifier import SklearnClassifier
from app.pipeline.cleaner import clean_ticket
from app.security.injection import detect_injection
from app.security.social_engineering import detect_social_engineering
from ml.train import RAW_CSV, TEST_PATH, train

TARGET_ACC, MIN_COVERAGE = 0.95, 0.60
THRESHOLDS = [round(t, 2) for t in np.arange(0.50, 0.951, 0.05)]
HANDWRITTEN = ROOT / "data" / "eval" / "handwritten_tickets.csv"
SUBTYPE_KB = {  # expected KB article per generator subtype (retrieval evaluation)
    "hw_no_boot": "KB0001", "hw_display": "KB0002", "hw_peripheral": "KB0003", "hw_slow": "KB0004", "hw_new_equipment": "KB0005",
    "nw_vpn": "KB0006", "nw_wifi": "KB0007", "nw_slow_lan": "KB0008", "nw_access_request": "KB0009",
    "ap_password_reset": "KB0010", "ap_locked": "KB0011", "ap_mfa": "KB0012", "ap_access_request": "KB0013",
    "sw_crash": "KB0014", "sw_install_request": "KB0015", "sw_license": "KB0016", "sw_update_fail": "KB0017",
    "em_send_receive": "KB0018", "em_mailbox_full": "KB0019", "em_dl_request": "KB0019",
    "pr_offline_jam": "KB0020", "pr_queue_quality": "KB0020", "pr_add_request": "KB0020",
}


def threshold_curve(conf: np.ndarray, correct: np.ndarray) -> list[dict]:
    out = []
    for t in THRESHOLDS:
        m = conf >= t
        out.append({"threshold": t, "coverage": float(m.mean()), "accuracy": float(correct[m].mean()) if m.any() else None,
                    "n_auto": int(m.sum())})
    return out


def choose_threshold(curve: list[dict]) -> dict:
    """Rule A: lowest threshold whose auto-routed accuracy >= 95%.
    Rule B (fallback, since label noise can cap accuracy): max auto-routed accuracy subject to coverage >= 60%."""
    for p in curve:
        if p["accuracy"] is not None and p["accuracy"] >= TARGET_ACC:
            return {"value": p["threshold"], "rule": "accuracy_target", "accuracy": p["accuracy"], "coverage": p["coverage"]}
    ok = [p for p in curve if p["accuracy"] is not None and p["coverage"] >= MIN_COVERAGE]
    if ok:
        best = max(ok, key=lambda p: (p["accuracy"], -p["threshold"]))
        return {"value": best["threshold"], "rule": "max_acc_cov60", "accuracy": best["accuracy"], "coverage": best["coverage"]}
    return {"value": 0.85, "rule": "default", "accuracy": None, "coverage": None}


def security_metrics() -> dict:
    df = pd.read_csv(RAW_CSV)
    dom = get_settings().corporate_domain
    se_p, inj_p = [], []
    for s, b, e in zip(df.subject, df.body, df.requester_email):
        text = clean_ticket(s, b).text
        se_p.append(detect_social_engineering(text, e, dom).flagged)
        inj_p.append(detect_injection(text).flagged)
    df["se_pred"], df["inj_pred"] = se_p, inj_p

    def prf(truth: pd.Series, pred: pd.Series, legit: pd.Series) -> dict:
        tp, fp, fn = int((truth & pred).sum()), int((~truth & pred).sum()), int((truth & ~pred).sum())
        return {"tp": tp, "fp": fp, "fn": fn, "precision": tp / (tp + fp) if tp + fp else None,
                "recall": tp / (tp + fn) if tp + fn else None,
                "false_positive_rate_on_legitimate": float((legit & pred).sum() / legit.sum()),
                "n_legitimate": int(legit.sum()), "n_positive": int(truth.sum())}

    legit = ~df.is_malicious
    se_t, inj_t = df.attack_type == "social_engineering", df.attack_type == "prompt_injection"
    decoys = df.scenario.str.startswith("decoy")
    return {
        "social_engineering": prf(se_t, df.se_pred, legit), "prompt_injection": prf(inj_t, df.inj_pred, legit),
        "combined": prf(df.is_malicious, df.se_pred | df.inj_pred, legit),
        "decoy_false_positives": df[decoys & (df.se_pred | df.inj_pred)].ticket_id.tolist(),
        "missed": df[df.is_malicious & ~(df.se_pred | df.inj_pred)].ticket_id.tolist(),
        "n_decoys": int(decoys.sum()),
    }


def main() -> dict:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if not (ARTIFACTS / "model.joblib").exists() or not TEST_PATH.exists():
        train()
    clf = SklearnClassifier()
    te = pd.read_csv(TEST_PATH)
    preds = clf.predict_many(te.text.tolist())
    y_pred = np.array([p.category for p in preds])
    conf = np.array([p.confidence for p in preds])
    correct = y_pred == te.category.values
    rep = classification_report(te.category, y_pred, labels=CATEGORIES, output_dict=True, zero_division=0)
    print(classification_report(te.category, y_pred, labels=CATEGORIES, zero_division=0))
    cm = confusion_matrix(te.category, y_pred, labels=CATEGORIES)
    print("Confusion matrix (rows=true, cols=pred):\n", pd.DataFrame(cm, CATEGORIES, CATEGORIES).to_string())

    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(6), CATEGORIES, rotation=40, ha="right")
    ax.set_yticks(range(6), CATEGORIES)
    for i in range(6):
        for j in range(6):
            ax.text(j, i, cm[i, j], ha="center", va="center", color="white" if cm[i, j] > cm.max() / 2 else "black")
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    ax.set_title("Confusion matrix (held-out test set)")
    fig.tight_layout()
    fig.savefig(ARTIFACTS / "confusion_matrix.png", dpi=130)
    plt.close(fig)

    curve = threshold_curve(conf, correct)
    pd.DataFrame(curve).to_csv(ARTIFACTS / "threshold_curve.csv", index=False)
    thr = choose_threshold(curve)
    print("\nCoverage vs accuracy:\n" + pd.DataFrame(curve).round(3).to_string(index=False))
    print(f"\nChosen threshold {thr['value']} via rule '{thr['rule']}' (auto-routed acc {thr['accuracy']:.3f}, coverage {thr['coverage']:.3f})")

    # --- ticket type, priority engine, KB retrieval (all on the held-out set)
    type_acc = float(np.mean([p.ticket_type == t for p, t in zip(preds, te.ticket_type)]))
    pr_pred = [priority.compute(t, p.ticket_type).priority for t, p in zip(te.text, preds)]
    order = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
    diff = np.abs(np.array([order[a] for a in pr_pred]) - np.array([order[b] for b in te.true_priority]))
    kb_hits = [(h := kb.suggest(t, p.category)) is not None and h.id == SUBTYPE_KB.get(s) for t, p, s in zip(te.text, preds, te.subtype)]

    # --- out-of-template (hand-written) evaluation, reported separately
    hw = pd.read_csv(HANDWRITTEN)
    hw["text"] = [clean_ticket(s, b).text for s, b in zip(hw.subject, hw.body)]
    hp = clf.predict_many(hw.text.tolist())
    handwritten = {"n": len(hw), "accuracy": float(np.mean([p.category == t for p, t in zip(hp, hw.true_category)])),
                   "ticket_type_accuracy": float(np.mean([p.ticket_type == t for p, t in zip(hp, hw.true_ticket_type)])),
                   "mean_confidence": float(np.mean([p.confidence for p in hp])),
                   "note": "n < 30: indicative only; add rows to data/eval/handwritten_tickets.csv" if len(hw) < 30 else ""}
    print(f"\nHand-written set: n={handwritten['n']} accuracy={handwritten['accuracy']:.2%} {handwritten['note']}")

    sec = security_metrics()
    for k in ("social_engineering", "prompt_injection", "combined"):
        s = sec[k]
        print(f"[{k}] precision={s['precision']} recall={s['recall']} FPR(on {s['n_legitimate']} legit)={s['false_positive_rate_on_legitimate']:.4f} tp={s['tp']} fp={s['fp']} fn={s['fn']}")

    fb_count = 0
    try:
        from app.db import session_scope
        from app.models import Feedback
        with session_scope() as s:
            fb_count = s.query(Feedback).count()
    except Exception:
        pass
    metrics = {
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"), "model_version": clf.version,
        "n_test": len(te), "accuracy": float(accuracy_score(te.category, y_pred)),
        "macro_f1": float(f1_score(te.category, y_pred, average="macro")), "ticket_type_accuracy": type_acc,
        "per_class": {c: rep[c] for c in CATEGORIES}, "confusion_matrix": cm.tolist(), "labels": CATEGORIES,
        "threshold": {**thr, "target_accuracy": TARGET_ACC, "min_coverage": MIN_COVERAGE}, "curve": curve,
        "priority": {"exact": float((diff == 0).mean()), "within_one": float((diff <= 1).mean())},
        "kb_hit_rate": float(np.mean(kb_hits)), "handwritten": handwritten, "security": sec,
        "feedback_count": fb_count,
    }
    (ARTIFACTS / "metrics.json").write_text(json.dumps(metrics, indent=2))
    print(f"\ncategory accuracy {metrics['accuracy']:.3f} | macro-F1 {metrics['macro_f1']:.3f} | ticket-type acc {type_acc:.3f} | "
          f"priority exact {metrics['priority']['exact']:.3f} (within one {metrics['priority']['within_one']:.3f}) | KB hit-rate {metrics['kb_hit_rate']:.3f}")
    return metrics


if __name__ == "__main__":
    main()
