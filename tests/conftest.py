"""Shared pytest fixtures.

Repository layout is encoded here and nowhere else in the test suite, so a
change to the directory structure is a one-line edit rather than a search.

Library code deliberately does not derive paths this way. Functions take paths
as arguments so tests can supply synthetic fixtures, and `load_data.py` at the
repository root resolves the real locations from its own position.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from cellcount.db import connect, create_schema
from cellcount.loader import POPULATIONS

REPO_ROOT = Path(__file__).parent.parent

# A hand-built dataset small enough to reason about entirely.
# Every sample totals 200 cells, so each percentage is just count / 2.
_SUBJECTS = [
    # subject_id, project, condition, age, sex, treatment, response
    ("sbj1", "prj1", "melanoma", 50, "M", "miraclib", "yes"),
    ("sbj2", "prj1", "melanoma", 60, "F", "miraclib", "no"),
    ("sbj3", "prj2", "carcinoma", 45, "M", "phauximab", "yes"),
]

_SAMPLES = [
    # sample_id, subject_id, sample_type, timepoint
    ("s1", "sbj1", "PBMC", 0),
    ("s2", "sbj1", "PBMC", 7),  # same subject as s1: repeated measures
    ("s3", "sbj2", "PBMC", 0),
    ("s4", "sbj3", "WB", 0),
]

_COUNTS = {
    # sample_id: counts in POPULATIONS order, each row summing to 200
    "s1": (10, 20, 30, 40, 100),
    "s2": (20, 20, 20, 20, 120),
    "s3": (50, 50, 50, 25, 25),
    "s4": (40, 40, 40, 40, 40),
}


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """An empty in-memory database, opened the same way the app opens one."""
    connection = connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def seeded_db(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Schema plus a tiny, predictable dataset.

    Built with direct inserts rather than through the loader, so a query test
    that fails points at the query rather than at CSV parsing.
    """
    create_schema(conn)
    with conn:
        conn.executemany(
            "INSERT INTO populations (population_id, name) VALUES (?, ?)",
            list(enumerate(POPULATIONS, start=1)),
        )
        conn.executemany(
            "INSERT INTO projects (project_id) VALUES (?)",
            [("prj1",), ("prj2",)],
        )
        conn.executemany(
            "INSERT INTO subjects "
            "(subject_id, project_id, condition, age, sex, treatment, response) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            _SUBJECTS,
        )
        conn.executemany(
            "INSERT INTO samples "
            "(sample_id, subject_id, sample_type, time_from_treatment_start) "
            "VALUES (?, ?, ?, ?)",
            _SAMPLES,
        )
        conn.executemany(
            "INSERT INTO cell_counts (sample_id, population_id, count) "
            "VALUES (?, ?, ?)",
            [
                (sample_id, index, counts[index - 1])
                for sample_id, counts in _COUNTS.items()
                for index in range(1, len(POPULATIONS) + 1)
            ],
        )
    return conn


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def cell_count_csv() -> Path:
    """The real input dataset.

    For characterization tests only. Behavioural tests should build small
    synthetic inputs instead, so they stay fast and their failures point at a
    bug rather than at the data.
    """
    return REPO_ROOT / "cell-count.csv"
