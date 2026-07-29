#!/usr/bin/env python3
"""Initialize the database and load cell-count.csv.

Run from the repository root, with no arguments:

    python load_data.py

This file is the one place that resolves real filesystem locations. It sits at
the repository root, so it can derive that root from its own position, and it
passes concrete paths into the library. Library code never guesses where it is,
which is what lets tests hand it synthetic inputs instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# The spec requires `python load_data.py` to work as a standalone invocation.
# Adding src/ to the path means it does so even before `make setup` performs the
# editable install, and is a no-op once the package is importable.
sys.path.insert(0, str(ROOT / "src"))

from cellcount.db import connect, create_schema  # noqa: E402
from cellcount.loader import load_csv  # noqa: E402

CSV_PATH = ROOT / "cell-count.csv"
DB_PATH = ROOT / "cell-count.db"


def main() -> None:
    # Rebuild from scratch so the schema always matches the current code, and
    # so re-running the pipeline is deterministic.
    DB_PATH.unlink(missing_ok=True)

    conn = connect(DB_PATH)
    try:
        create_schema(conn)
        summary = load_csv(conn, CSV_PATH)
    finally:
        conn.close()

    print(f"Loaded {CSV_PATH.name} -> {DB_PATH.name}")
    print(f"  projects     {summary.projects:>7,}")
    print(f"  subjects     {summary.subjects:>7,}")
    print(f"  samples      {summary.samples:>7,}")
    print(f"  cell counts  {summary.cell_counts:>7,}")


if __name__ == "__main__":
    main()
