"""Load cell-count.csv into the database.

The loader validates before it writes. Two classes of problem are worth
catching here rather than downstream:

Attributes the schema stores once per subject must not disagree across that
subject's samples. If they did, writing one of them would silently discard the
others, and nothing downstream could detect the loss.

Counts must be non-negative integers. The schema enforces this too, but raising
here names the offending column and sample, which an IntegrityError does not.

Loading is idempotent: existing rows are cleared first, so the CSV is the single
source of truth and `make pipeline` can be re-run freely.
"""

from __future__ import annotations

import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path

POPULATIONS = ("b_cell", "cd8_t_cell", "cd4_t_cell", "nk_cell", "monocyte")

REQUIRED_COLUMNS = (
    "project",
    "subject",
    "condition",
    "age",
    "sex",
    "treatment",
    "response",
    "sample",
    "sample_type",
    "time_from_treatment_start",
    *POPULATIONS,
)

# Stored once per subject, so they must be identical across that subject's rows.
SUBJECT_COLUMNS = ("project", "condition", "age", "sex", "treatment", "response")


class DataValidationError(ValueError):
    """The input file violates an assumption the schema depends on."""


@dataclass(frozen=True)
class LoadSummary:
    projects: int
    subjects: int
    samples: int
    cell_counts: int


def _read_rows(csv_path: Path) -> list[dict[str, str]]:
    # utf-8-sig so a byte-order mark does not turn the first header into
    # '﻿project' and surface as a confusing missing-column error.
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise DataValidationError(f"missing required column(s): {missing}")
        return list(reader)


def _parse_int(raw: str, *, field: str, sample: str) -> int:
    """Parse an integer, naming the offending field if it is not one.

    `str.isdigit` is not a substitute: it accepts superscripts like '²', and
    stripping a leading '-' first lets '--5' through. Both then fail inside
    int() mid-write, which is exactly what validating up front is meant to
    prevent.
    """
    try:
        return int(raw)
    except ValueError:
        raise DataValidationError(
            f"sample {sample}: {field} is not an integer: {raw!r}"
        ) from None


def _validate_unique_samples(rows: list[dict[str, str]]) -> None:
    seen: set[str] = set()
    for row in rows:
        sample = row["sample"]
        if sample in seen:
            raise DataValidationError(f"duplicate sample id: {sample!r}")
        seen.add(sample)


def _validate_counts(rows: list[dict[str, str]]) -> None:
    for row in rows:
        sample = row["sample"]
        total = 0
        for population in POPULATIONS:
            value = _parse_int(row[population], field=population, sample=sample)
            if value < 0:
                raise DataValidationError(
                    f"sample {sample}: {population} is negative: {value}"
                )
            total += value
        if total == 0:
            raise DataValidationError(
                f"sample {sample}: every population is zero, so relative "
                f"frequency is undefined"
            )


def _validate_numeric_metadata(rows: list[dict[str, str]]) -> None:
    """Age and timepoint are written as integers, so they are checked as integers."""
    for row in rows:
        sample = row["sample"]
        if row["age"]:
            _parse_int(row["age"], field="age", sample=sample)
        _parse_int(
            row["time_from_treatment_start"],
            field="time_from_treatment_start",
            sample=sample,
        )


def _validate_subject_attributes(rows: list[dict[str, str]]) -> None:
    seen: dict[str, dict[str, str]] = {}
    for row in rows:
        subject = row["subject"]
        first = seen.setdefault(subject, {c: row[c] for c in SUBJECT_COLUMNS})
        for column in SUBJECT_COLUMNS:
            if first[column] != row[column]:
                raise DataValidationError(
                    f"subject {subject}: {column} varies across samples "
                    f"({first[column]!r} then {row[column]!r}), so it cannot be "
                    f"stored once per subject"
                )


def _clear(conn: sqlite3.Connection) -> None:
    # Children before parents, so foreign keys stay satisfied throughout.
    for table in ("cell_counts", "samples", "subjects", "projects", "populations"):
        conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names


def load_csv(conn: sqlite3.Connection, csv_path: Path) -> LoadSummary:
    """Replace the contents of the database with the rows in `csv_path`."""
    rows = _read_rows(csv_path)
    _validate_unique_samples(rows)
    _validate_counts(rows)
    _validate_numeric_metadata(rows)
    _validate_subject_attributes(rows)

    population_ids = {name: index for index, name in enumerate(POPULATIONS, start=1)}

    with conn:
        _clear(conn)

        conn.executemany(
            "INSERT INTO populations (population_id, name) VALUES (?, ?)",
            [(pid, name) for name, pid in population_ids.items()],
        )
        conn.executemany(
            "INSERT INTO projects (project_id) VALUES (?)",
            [(p,) for p in sorted({row["project"] for row in rows})],
        )

        subjects = {row["subject"]: row for row in rows}
        conn.executemany(
            "INSERT INTO subjects "
            "(subject_id, project_id, condition, age, sex, treatment, response) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    subject,
                    row["project"],
                    row["condition"],
                    int(row["age"]) if row["age"] else None,
                    row["sex"],
                    row["treatment"] or None,
                    # Empty means "not applicable", e.g. an untreated control.
                    row["response"] or None,
                )
                for subject, row in subjects.items()
            ],
        )
        conn.executemany(
            "INSERT INTO samples "
            "(sample_id, subject_id, sample_type, time_from_treatment_start) "
            "VALUES (?, ?, ?, ?)",
            [
                (
                    row["sample"],
                    row["subject"],
                    row["sample_type"],
                    int(row["time_from_treatment_start"]),
                )
                for row in rows
            ],
        )
        conn.executemany(
            "INSERT INTO cell_counts (sample_id, population_id, count) "
            "VALUES (?, ?, ?)",
            [
                (row["sample"], population_ids[population], int(row[population]))
                for row in rows
                for population in POPULATIONS
            ],
        )

    return LoadSummary(
        projects=len({row["project"] for row in rows}),
        subjects=len(subjects),
        samples=len(rows),
        cell_counts=len(rows) * len(POPULATIONS),
    )
