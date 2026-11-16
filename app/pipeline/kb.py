"""Step 7 - Suggest fix: TF-IDF cosine retrieval over the markdown KB in data/kb/."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from app.config import ROOT, get_settings

KB_DIR = ROOT / "data" / "kb"
MIN_SCORE = 0.12  # below this the article is not relevant enough to attach


@dataclass
class Article:
    id: str
    title: str
    category: str
    body: str


@dataclass
class KBHit:
    id: str
    title: str
    score: float
    url: str


def _parse(path) -> Article:
    raw = path.read_text(encoding="utf-8")
    _, fm, body = raw.split("---", 2)
    meta = dict(line.split(": ", 1) for line in fm.strip().splitlines())
    return Article(meta["id"], meta["title"], meta["category"], body.strip())


@lru_cache(maxsize=1)
def _index():
    arts = [_parse(p) for p in sorted(KB_DIR.glob("KB*.md"))]
    vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
    # title weighted x3 so symptom-style queries match article names
    mat = vec.fit_transform([f"{(a.title + ' ') * 3}{a.body}" for a in arts])
    return arts, vec, mat


def get_article(kb_id: str) -> Article | None:
    return next((a for a in _index()[0] if a.id == kb_id), None)


def suggest(text: str, category: str | None = None) -> KBHit | None:
    arts, vec, mat = _index()
    sims = linear_kernel(vec.transform([text]), mat).ravel()
    if category:  # mild preference for articles from the predicted category
        sims = sims * [1.15 if a.category == category else 1.0 for a in arts]
    i = int(sims.argmax())
    if sims[i] < MIN_SCORE:
        return None
    return KBHit(arts[i].id, arts[i].title, float(sims[i]), f"{get_settings().api_url}/kb/{arts[i].id}")
