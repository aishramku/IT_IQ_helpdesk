"""Step 3 - Classify with the saved calibrated sklearn model (category + ticket type + confidence)."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import joblib
import numpy as np

from app.config import ARTIFACTS

MODEL_PATH = ARTIFACTS / "model.joblib"


@dataclass
class Prediction:
    category: str
    confidence: float
    ticket_type: str
    type_confidence: float


class SklearnClassifier:
    def __init__(self, path=MODEL_PATH) -> None:
        if not path.exists():
            raise FileNotFoundError(f"{path} missing - run `python -m ml.train` first")
        b = joblib.load(path)
        self.vec, self.cat, self.typ = b["vectorizer"], b["cat_model"], b["type_model"]
        self.version: str = b["version"]

    def predict_many(self, texts: list[str]) -> list[Prediction]:
        X = self.vec.transform(texts)
        pc, pt = self.cat.predict_proba(X), self.typ.predict_proba(X)
        ci, ti = pc.argmax(1), pt.argmax(1)
        return [Prediction(str(self.cat.classes_[c]), float(pc[i, c]), str(self.typ.classes_[t]), float(pt[i, t]))
                for i, (c, t) in enumerate(zip(ci, ti))]

    def predict(self, text: str) -> Prediction:
        return self.predict_many([text])[0]

    def proba(self, texts: list[str]) -> tuple[np.ndarray, np.ndarray]:
        X = self.vec.transform(texts)
        return self.cat.predict_proba(X), self.cat.classes_


@lru_cache(maxsize=1)
def get_classifier() -> SklearnClassifier:
    return SklearnClassifier()


def reload_classifier() -> SklearnClassifier:  # after retraining
    get_classifier.cache_clear()
    return get_classifier()
