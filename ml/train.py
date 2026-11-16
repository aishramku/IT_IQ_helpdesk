"""Train the calibrated TF-IDF + Logistic Regression classifier (category + ticket_type heads).

    python -m ml.train            # trains, saves model.joblib + test_set.csv, then run ml.evaluate

Modelling set excludes tickets that are not classification problems: attack_* (handled by the
security screen) and outage/duplicate rows (near-identical copies would leak across the split).
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_union

from app.config import ARTIFACTS, ROOT
from app.pipeline.cleaner import clean_ticket

RAW_CSV = ROOT / "data" / "raw" / "tickets.csv"
MODEL_PATH = ARTIFACTS / "model.joblib"
TEST_PATH = ARTIFACTS / "test_set.csv"
SEED = 42
EXCLUDED = ("outage", "duplicate")


def build_frame(csv: Path = RAW_CSV) -> pd.DataFrame:
    df = pd.read_csv(csv)
    df = df[~df.scenario.isin(EXCLUDED) & ~df.scenario.str.startswith("attack")].copy()
    df["text"] = [clean_ticket(s, b).text for s, b in zip(df.subject, df.body)]
    return df.rename(columns={"true_category": "category", "true_ticket_type": "ticket_type"})[
        ["ticket_id", "text", "category", "ticket_type", "subtype", "scenario", "true_priority"]].reset_index(drop=True)


def _head() -> CalibratedClassifierCV:
    # isotonic calibration makes `max predict_proba` an honest confidence for the routing threshold
    return CalibratedClassifierCV(LogisticRegression(C=8, max_iter=3000), method="isotonic", cv=5)


def fit(train_df: pd.DataFrame) -> dict:
    vec = make_union(
        TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, strip_accents="unicode"),
        TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True, max_features=40000),  # typo-robust
    )
    X = vec.fit_transform(train_df.text)
    cat = _head().fit(X, train_df.category)
    typ = _head().fit(X, train_df.ticket_type)
    return {"vectorizer": vec, "cat_model": cat, "type_model": typ, "n_train": len(train_df),
            "version": f"tfidf-lr-cal-{datetime.utcnow():%Y%m%d%H%M}", "trained_at": datetime.utcnow().isoformat(timespec="seconds")}


def split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    return train_test_split(df, test_size=0.2, stratify=df.category, random_state=SEED)


def train(extra: pd.DataFrame | None = None, save: bool = True, csv: Path = RAW_CSV) -> tuple[dict, pd.DataFrame]:
    """`extra` rows (e.g. agent feedback) are added to the TRAIN side only; the test set stays fixed."""
    tr, te = split(build_frame(csv))
    if extra is not None and len(extra):
        tr = pd.concat([tr[~tr.ticket_id.isin(extra.ticket_id)], extra[tr.columns.intersection(extra.columns)]], ignore_index=True)
    bundle = fit(tr)
    if save:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle, MODEL_PATH)
        te.to_csv(TEST_PATH, index=False)
    return bundle, te


if __name__ == "__main__":
    argparse.ArgumentParser().parse_args()
    b, te = train()
    print(f"trained {b['version']} on {b['n_train']} tickets; held-out test set: {len(te)} -> {MODEL_PATH}")
