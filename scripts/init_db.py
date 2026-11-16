"""Create (or --reset) all tables.   python -m scripts.init_db [--reset]"""
from __future__ import annotations

import argparse

from app.db import engine
from app.models import Base


def init_db(reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="drop all tables first")
    a = ap.parse_args()
    init_db(a.reset)
    print(f"database ready: {engine.url.render_as_string(hide_password=True)}")
