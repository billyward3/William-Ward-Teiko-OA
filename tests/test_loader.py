"""Tests for the CSV loader.

Every test builds a small synthetic CSV rather than reading the real file, so a
failure points at the loader rather than at 10,500 rows of data. Assertions
about the real file live in `test_data_characteristics.py`.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

import pytest

from cellcount.db import create_schema
from cellcount.loader import DataValidationError, load_csv

HEADER = [
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
    "b_cell",
    "cd8_t_cell",
    "cd4_t_cell",
    "nk_cell",
    "monocyte",
]


def _row(
    *,
    project: str = "prj1",
    subject: str = "sbj1",
    condition: str = "melanoma",
    age: str = "50",
    sex: str = "M",
    treatment: str = "miraclib",
    response: str = "yes",
    sample: str = "s1",
    sample_type: str = "PBMC",
    time: str = "0",
    counts: tuple[str, str, str, str, str] = ("10", "20", "30", "40", "50"),
) -> list[str]:
    return [
        project,
        subject,
        condition,
        age,
        sex,
        treatment,
        response,
        sample,
        sample_type,
        time,
        *counts,
    ]


def _write_csv(tmp_path: Path, rows: list[list[str]]) -> Path:
    path = tmp_path / "cells.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path


@pytest.fixture
def db(conn: sqlite3.Connection) -> sqlite3.Connection:
    create_schema(conn)
    return conn


def _scalar(conn: sqlite3.Connection, sql: str) -> int:
    result: int = conn.execute(sql).fetchone()[0]
    return result


def test_load_populates_every_table(db: sqlite3.Connection, tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path,
        [
            _row(subject="sbj1", sample="s1", time="0"),
            _row(subject="sbj1", sample="s2", time="7"),
            _row(subject="sbj2", sample="s3", project="prj2"),
        ],
    )
    load_csv(db, path)

    assert _scalar(db, "SELECT COUNT(*) FROM projects") == 2
    assert _scalar(db, "SELECT COUNT(*) FROM subjects") == 2
    assert _scalar(db, "SELECT COUNT(*) FROM samples") == 3
    assert _scalar(db, "SELECT COUNT(*) FROM populations") == 5


def test_counts_are_stored_long(db: sqlite3.Connection, tmp_path: Path) -> None:
    """One row per sample and population, not five columns on the sample."""
    path = _write_csv(tmp_path, [_row(counts=("11", "22", "33", "44", "55"))])
    load_csv(db, path)

    assert _scalar(db, "SELECT COUNT(*) FROM cell_counts") == 5
    stored = dict(
        db.execute(
            "SELECT p.name, c.count FROM cell_counts c "
            "JOIN populations p USING (population_id)"
        )
    )
    assert stored == {
        "b_cell": 11,
        "cd8_t_cell": 22,
        "cd4_t_cell": 33,
        "nk_cell": 44,
        "monocyte": 55,
    }


def test_load_is_idempotent(db: sqlite3.Connection, tmp_path: Path) -> None:
    path = _write_csv(tmp_path, [_row(), _row(subject="sbj2", sample="s2")])
    load_csv(db, path)
    load_csv(db, path)

    assert _scalar(db, "SELECT COUNT(*) FROM samples") == 2
    assert _scalar(db, "SELECT COUNT(*) FROM cell_counts") == 10


def test_blank_response_becomes_null(db: sqlite3.Connection, tmp_path: Path) -> None:
    """Healthy controls have no response to assess; that is NULL, not empty string."""
    path = _write_csv(
        tmp_path, [_row(condition="healthy", treatment="none", response="")]
    )
    load_csv(db, path)

    assert _scalar(db, "SELECT COUNT(*) FROM subjects WHERE response IS NULL") == 1


def test_treatment_none_is_preserved_as_a_value(
    db: sqlite3.Connection, tmp_path: Path
) -> None:
    """'none' means untreated, which is information, unlike a missing response."""
    path = _write_csv(
        tmp_path, [_row(condition="healthy", treatment="none", response="")]
    )
    load_csv(db, path)

    assert _scalar(db, "SELECT COUNT(*) FROM subjects WHERE treatment = 'none'") == 1


def test_raises_when_a_subject_attribute_varies(
    db: sqlite3.Connection, tmp_path: Path
) -> None:
    """Storing these once per subject is only valid if they never disagree."""
    path = _write_csv(
        tmp_path,
        [
            _row(subject="sbj1", sample="s1", response="yes"),
            _row(subject="sbj1", sample="s2", time="7", response="no"),
        ],
    )
    with pytest.raises(DataValidationError, match="response"):
        load_csv(db, path)


def test_raises_on_non_integer_count(db: sqlite3.Connection, tmp_path: Path) -> None:
    path = _write_csv(tmp_path, [_row(counts=("10", "20", "not-a-number", "40", "50"))])
    with pytest.raises(DataValidationError, match="cd4_t_cell"):
        load_csv(db, path)


def test_raises_on_negative_count(db: sqlite3.Connection, tmp_path: Path) -> None:
    path = _write_csv(tmp_path, [_row(counts=("10", "20", "-1", "40", "50"))])
    with pytest.raises(DataValidationError):
        load_csv(db, path)


def test_raises_on_a_double_signed_count(
    db: sqlite3.Connection, tmp_path: Path
) -> None:
    """'--5'.lstrip('-') is '5', which isdigit() accepts. int() then fails."""
    path = _write_csv(tmp_path, [_row(counts=("--5", "20", "30", "40", "50"))])
    with pytest.raises(DataValidationError):
        load_csv(db, path)


def test_raises_on_a_unicode_digit_count(
    db: sqlite3.Connection, tmp_path: Path
) -> None:
    """'²'.isdigit() is True but int('²') raises."""
    path = _write_csv(tmp_path, [_row(counts=("²", "20", "30", "40", "50"))])
    with pytest.raises(DataValidationError):
        load_csv(db, path)


def test_raises_on_non_integer_age(db: sqlite3.Connection, tmp_path: Path) -> None:
    path = _write_csv(tmp_path, [_row(age="fifty")])
    with pytest.raises(DataValidationError, match="age"):
        load_csv(db, path)


def test_raises_on_non_integer_timepoint(
    db: sqlite3.Connection, tmp_path: Path
) -> None:
    path = _write_csv(tmp_path, [_row(time="baseline")])
    with pytest.raises(DataValidationError, match="time_from_treatment_start"):
        load_csv(db, path)


def test_raises_on_duplicate_sample_id(db: sqlite3.Connection, tmp_path: Path) -> None:
    """A named error beats an IntegrityError surfacing from mid-transaction."""
    path = _write_csv(
        tmp_path,
        [_row(sample="s1"), _row(subject="sbj2", sample="s1", time="7")],
    )
    with pytest.raises(DataValidationError, match="s1"):
        load_csv(db, path)


def test_raises_on_a_sample_with_no_cells(
    db: sqlite3.Connection, tmp_path: Path
) -> None:
    """Zero cells across every population is a failed acquisition, not data.

    It also makes the relative frequency undefined, so it cannot be loaded.
    """
    path = _write_csv(tmp_path, [_row(counts=("0", "0", "0", "0", "0"))])
    with pytest.raises(DataValidationError, match="zero"):
        load_csv(db, path)


def test_nothing_is_written_when_validation_fails(
    db: sqlite3.Connection, tmp_path: Path
) -> None:
    """Validation runs before the transaction, so a bad file leaves no partial load."""
    path = _write_csv(
        tmp_path,
        [_row(sample="good"), _row(subject="sbj2", sample="bad", age="fifty")],
    )
    with pytest.raises(DataValidationError):
        load_csv(db, path)
    assert _scalar(db, "SELECT COUNT(*) FROM samples") == 0


def test_raises_on_missing_column(db: sqlite3.Connection, tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["subject", "sample"])
        writer.writerow(["sbj1", "s1"])

    with pytest.raises(DataValidationError, match="column"):
        load_csv(db, path)


def test_returns_summary_of_rows_written(
    db: sqlite3.Connection, tmp_path: Path
) -> None:
    path = _write_csv(
        tmp_path,
        [_row(), _row(subject="sbj2", sample="s2", project="prj2")],
    )
    summary = load_csv(db, path)

    assert summary.projects == 2
    assert summary.subjects == 2
    assert summary.samples == 2
    assert summary.cell_counts == 10
