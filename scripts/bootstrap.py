"""One command to build everything:   python -m scripts.bootstrap

generate synthetic tickets -> load DB -> train model -> evaluate (writes metrics.json + threshold)
-> run the pipeline + duplicate/incident detection over the history.
"""
from __future__ import annotations

import subprocess
import sys

STEPS = [
    ("Generating 3,000 synthetic tickets", ["-m", "data.generator.generate_tickets"]),
    ("Loading history into the database", ["-m", "scripts.load_history", "--reset"]),
    ("Training the calibrated classifier", ["-m", "ml.train"]),
    ("Evaluating model, threshold curve and detectors", ["-m", "ml.evaluate"]),
    ("Processing the history through the pipeline", ["-m", "scripts.process_backlog"]),
]

if __name__ == "__main__":
    for title, args in STEPS:
        print(f"\n=== {title} ===", flush=True)
        if subprocess.call([sys.executable, "-W", "ignore", *args]) != 0:
            sys.exit(f"step failed: {title}")
    print("\nDone. Start the dashboard:  streamlit run dashboard/Home.py\n      and the API:        uvicorn app.main:app")
