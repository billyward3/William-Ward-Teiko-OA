"""Tests for the database schema.

These define the constraints the schema is expected to enforce. A constraint
that is not tested here is not guaranteed, because SQLite silently accepts a
surprising amount by default: foreign keys in particular are off unless the
connection turns them on.
"""

from __future__ import annotations

import sqlite3

import pytest

from cellcount.db import create_schema

EXPECTED_TABLES = ["cell_counts", "populations", "projects", "samples", "subjects"]


def _seed_minimal(conn: sqlite3.Connection) -> None:
    """One project, subject, and population, so samples have something to hang off."""
    conn.execute("INSERT INTO projects (project_id) VALUES ('prj1')")
    conn.execute(
        "INSERT INTO subjects (subject_id, project_id, condition, sex) "
        "VALUES ('sbj1', 'prj1', 'melanoma', 'M')"
    )
    conn.execute("INSERT INTO populations (population_id, name) VALUES (1, 'b_cell')")


def test_create_schema_creates_expected_tables(conn: sqlite3.Connection) -> None:
    create_schema(conn)
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
    ]
    assert names == EXPECTED_TABLES


def test_create_schema_is_idempotent(conn: sqlite3.Connection) -> None:
    create_schema(conn)
    create_schema(conn)


def test_foreign_keys_are_enforced(conn: sqlite3.Connection) -> None:
    """SQLite defaults this off, so it is a property of how we connect."""
    create_schema(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO samples "
            "(sample_id, subject_id, sample_type, time_from_treatment_start) "
            "VALUES ('s1', 'nonexistent-subject', 'PBMC', 0)"
        )


def test_sample_is_unique_per_subject_type_and_timepoint(
    conn: sqlite3.Connection,
) -> None:
    create_schema(conn)
    _seed_minimal(conn)
    conn.execute(
        "INSERT INTO samples "
        "(sample_id, subject_id, sample_type, time_from_treatment_start) "
        "VALUES ('s1', 'sbj1', 'PBMC', 0)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO samples "
            "(sample_id, subject_id, sample_type, time_from_treatment_start) "
            "VALUES ('s2', 'sbj1', 'PBMC', 0)"
        )


def test_population_names_are_unique(conn: sqlite3.Connection) -> None:
    create_schema(conn)
    _seed_minimal(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO populations (population_id, name) VALUES (2, 'b_cell')"
        )


def test_cell_count_must_be_non_negative(conn: sqlite3.Connection) -> None:
    create_schema(conn)
    _seed_minimal(conn)
    conn.execute(
        "INSERT INTO samples "
        "(sample_id, subject_id, sample_type, time_from_treatment_start) "
        "VALUES ('s1', 'sbj1', 'PBMC', 0)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO cell_counts (sample_id, population_id, count) "
            "VALUES ('s1', 1, -1)"
        )


def test_one_count_per_sample_and_population(conn: sqlite3.Connection) -> None:
    create_schema(conn)
    _seed_minimal(conn)
    conn.execute(
        "INSERT INTO samples "
        "(sample_id, subject_id, sample_type, time_from_treatment_start) "
        "VALUES ('s1', 'sbj1', 'PBMC', 0)"
    )
    conn.execute(
        "INSERT INTO cell_counts (sample_id, population_id, count) VALUES ('s1', 1, 10)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO cell_counts (sample_id, population_id, count) "
            "VALUES ('s1', 1, 20)"
        )
