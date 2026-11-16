"""Text similarity shared by duplicate and incident detection (word+char TF-IDF, cosine)."""
from __future__ import annotations

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def _vectorizer():
    try:  # reuse the fitted classifier vectorizer (typo-robust, stable feature space)
        from app.pipeline.classifier import get_classifier
        return get_classifier().vec
    except FileNotFoundError:
        return None


def sims_to(anchor: str, others: list[str]) -> np.ndarray:
    """Cosine similarity of `anchor` against each text in `others`."""
    if not others:
        return np.array([])
    vec = _vectorizer()
    if vec is None:  # model not trained (e.g. unit tests): fit on the fly
        vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True).fit([anchor, *others])
    return cosine_similarity(vec.transform([anchor]), vec.transform(others)).ravel()
