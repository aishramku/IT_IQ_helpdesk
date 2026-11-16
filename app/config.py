"""Runtime configuration (12-factor: everything comes from env / .env)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / "ml" / "artifacts"
DEFAULT_THRESHOLD = 0.85  # used only until ml/evaluate.py has chosen a data-driven one


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # Swapping SQLite -> PostgreSQL is only this URL (see .env.example).
    database_url: str = ""
    use_llm: bool = False
    anthropic_api_key: str = ""
    llm_model: str = "claude-haiku-5-5"

    confidence_threshold: float | None = None
    corporate_domain: str = "acmecorp.com"
    incident_window_minutes: int = 15
    incident_min_distinct_requesters: int = 10
    duplicate_similarity: float = 0.72  # follow-ups prepend text ("any update?"); 0.80 missed 5/30 (sims 0.74-0.79)
    incident_similarity: float = 0.50  # outage reports are worded differently (median pairwise sim 0.45); normal traffic never exceeds 2 distinct similar requesters even at 0.40
    api_url: str = "http://127.0.0.1:8000"

    @field_validator("confidence_threshold", mode="before")
    @classmethod
    def _blank_to_none(cls, v):  # `CONFIDENCE_THRESHOLD=` in .env means "unset"
        return None if v in ("", None) else v

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(ROOT / 'data' / 'triageiq.db').as_posix()}"

    @property
    def threshold(self) -> float:
        """Env override > threshold chosen by evaluate.py > conservative default."""
        if self.confidence_threshold is not None:
            return self.confidence_threshold
        try:
            return float(json.loads((ARTIFACTS / "metrics.json").read_text())["threshold"]["value"])
        except (OSError, KeyError, ValueError, TypeError):
            return DEFAULT_THRESHOLD


@lru_cache
def get_settings() -> Settings:
    return Settings()
