"""Database connection and schema.

The shape is a star schema: `cell_counts` is the fact table, and `projects`,
`subjects`, `samples`, and `populations` are dimensions.

Counts are stored long, one row per sample and population, rather than as five
columns on `samples`. Adding a sixth population is then an INSERT into
`populations` instead of a schema migration, and Part 2's required output shape
falls out of the storage rather than needing an unpivot.

Attributes constant within a subject live on `subjects` rather than repeating on
every sample. `tests/test_data_characteristics.py` verifies that invariant against
the real file, and the loader re-checks it on every run.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS projects (
    project_id  TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS subjects (
    subject_id  TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(project_id),
    condition   TEXT NOT NULL,
    age         INTEGER,
    sex         TEXT NOT NULL,
    -- 'none' for untreated subjects; NULL only if genuinely unknown.
    treatment   TEXT,
    -- NULL where response is not applicable, e.g. healthy controls.
    response    TEXT
);

CREATE TABLE IF NOT EXISTS populations (
    population_id  INTEGER PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS samples (
    sample_id                  TEXT PRIMARY KEY,
    subject_id                 TEXT NOT NULL REFERENCES subjects(subject_id),
    sample_type                TEXT NOT NULL,
    time_from_treatment_start  INTEGER NOT NULL,
    -- Natural key alongside the surrogate id: a subject cannot have two
    -- samples of the same type at the same timepoint.
    UNIQUE (subject_id, sample_type, time_from_treatment_start)
);

CREATE TABLE IF NOT EXISTS cell_counts (
    sample_id      TEXT    NOT NULL REFERENCES samples(sample_id),
    population_id  INTEGER NOT NULL REFERENCES populations(population_id),
    count          INTEGER NOT NULL CHECK (count >= 0),
    PRIMARY KEY (sample_id, population_id)
);

CREATE INDEX IF NOT EXISTS idx_subjects_project
    ON subjects(project_id);
CREATE INDEX IF NOT EXISTS idx_subjects_filters
    ON subjects(condition, treatment, response, sex);
CREATE INDEX IF NOT EXISTS idx_samples_subject
    ON samples(subject_id);
CREATE INDEX IF NOT EXISTS idx_samples_filters
    ON samples(sample_type, time_from_treatment_start);
CREATE INDEX IF NOT EXISTS idx_cell_counts_population
    ON cell_counts(population_id);
"""


def connect(database: str | Path) -> sqlite3.Connection:
    """Open a connection with foreign key enforcement on.

    SQLite disables foreign keys by default, per connection rather than per
    database, so every caller has to opt in. Routing all connections through
    here means no code path can silently skip it.
    """
    conn = sqlite3.connect(database)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they do not already exist."""
    conn.executescript(SCHEMA_SQL)
