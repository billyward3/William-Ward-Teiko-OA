"""Tests for absolute population means.

This exists for the submission form's question, which is deliberately worded to
differ from Part 4 in three ways: melanoma males across **all** sample types and
**all** treatments, and an **absolute count** rather than a relative frequency.

Reusing the Part 4 cohort produces a confident wrong answer, so the tests below
pin each of those three differences separately.
"""

from __future__ import annotations

import sqlite3

import pytest

from cellcount.cohort import Cohort
from cellcount.db import create_schema
from cellcount.loader import POPULATIONS
from cellcount.means import mean_count


def _add_sample(
    conn: sqlite3.Connection,
    subject: str,
    *,
    counts: tuple[int, int, int, int, int],
    sex: str = "M",
    condition: str = "melanoma",
    treatment: str = "miraclib",
    response: str | None = "yes",
    sample_type: str = "PBMC",
    timepoint: int = 0,
) -> None:
    conn.execute("INSERT OR IGNORE INTO projects (project_id) VALUES ('prj1')")
    conn.execute(
        "INSERT INTO subjects "
        "(subject_id, project_id, condition, age, sex, treatment, response) "
        "VALUES (?, 'prj1', ?, 50, ?, ?, ?)",
        (subject, condition, sex, treatment, response),
    )
    sample = f"{subject}-s"
    conn.execute(
        "INSERT INTO samples (sample_id, subject_id, sample_type, "
        "time_from_treatment_start) VALUES (?, ?, ?, ?)",
        (sample, subject, sample_type, timepoint),
    )
    conn.executemany(
        "INSERT INTO cell_counts (sample_id, population_id, count) VALUES (?, ?, ?)",
        [(sample, i + 1, counts[i]) for i in range(len(POPULATIONS))],
    )


@pytest.fixture
def db(conn: sqlite3.Connection) -> sqlite3.Connection:
    create_schema(conn)
    conn.executemany(
        "INSERT INTO populations (population_id, name) VALUES (?, ?)",
        list(enumerate(POPULATIONS, start=1)),
    )
    return conn


def test_returns_the_arithmetic_mean_of_raw_counts(db: sqlite3.Connection) -> None:
    _add_sample(db, "a", counts=(100, 0, 0, 0, 0))
    _add_sample(db, "b", counts=(200, 0, 0, 0, 0))
    db.commit()

    assert mean_count(db, Cohort(), "b_cell") == 150.0


def test_the_mean_is_of_counts_not_percentages(db: sqlite3.Connection) -> None:
    """Both samples are 50% b_cell but have very different counts."""
    _add_sample(db, "a", counts=(50, 50, 0, 0, 0))
    _add_sample(db, "b", counts=(500, 500, 0, 0, 0))
    db.commit()

    assert mean_count(db, Cohort(), "b_cell") == 275.0


def test_sample_type_is_not_filtered_unless_asked(db: sqlite3.Connection) -> None:
    """The form question spans all sample types; Part 4 restricts to PBMC."""
    _add_sample(db, "a", counts=(100, 0, 0, 0, 0), sample_type="PBMC")
    _add_sample(db, "b", counts=(300, 0, 0, 0, 0), sample_type="WB")
    db.commit()

    assert mean_count(db, Cohort(), "b_cell") == 200.0
    assert mean_count(db, Cohort(sample_type="PBMC"), "b_cell") == 100.0


def test_treatment_is_not_filtered_unless_asked(db: sqlite3.Connection) -> None:
    """The form question spans all treatments; Part 4 restricts to miraclib."""
    _add_sample(db, "a", counts=(100, 0, 0, 0, 0), treatment="miraclib")
    _add_sample(db, "b", counts=(300, 0, 0, 0, 0), treatment="phauximab")
    db.commit()

    assert mean_count(db, Cohort(), "b_cell") == 200.0
    assert mean_count(db, Cohort(treatment="miraclib"), "b_cell") == 100.0


def test_every_cohort_field_narrows_the_mean(db: sqlite3.Connection) -> None:
    _add_sample(db, "a", counts=(100, 0, 0, 0, 0), sex="M", response="yes", timepoint=0)
    _add_sample(db, "b", counts=(900, 0, 0, 0, 0), sex="F", response="yes", timepoint=0)
    _add_sample(db, "c", counts=(900, 0, 0, 0, 0), sex="M", response="no", timepoint=0)
    _add_sample(db, "d", counts=(900, 0, 0, 0, 0), sex="M", response="yes", timepoint=7)
    db.commit()

    cohort = Cohort(sex="M", response="yes", timepoints=(0,))
    assert mean_count(db, cohort, "b_cell") == 100.0


def test_each_population_is_independent(db: sqlite3.Connection) -> None:
    _add_sample(db, "a", counts=(10, 20, 30, 40, 50))
    db.commit()

    assert mean_count(db, Cohort(), "b_cell") == 10.0
    assert mean_count(db, Cohort(), "monocyte") == 50.0


def test_repeated_counts_each_contribute(db: sqlite3.Connection) -> None:
    """AVG must not deduplicate.

    Every other fixture here uses distinct counts, which makes AVG(DISTINCT)
    invisible. The real form cohort has 485 samples but only 473 distinct
    b_cell values, so deduplicating changes the submitted answer.
    """
    _add_sample(db, "a", counts=(100, 10, 10, 10, 10))
    _add_sample(db, "b", counts=(100, 10, 10, 10, 10))
    _add_sample(db, "c", counts=(200, 10, 10, 10, 10))
    db.commit()

    assert mean_count(db, Cohort(), "b_cell") == pytest.approx(400 / 3)


def test_the_mean_keeps_fractional_precision(db: sqlite3.Connection) -> None:
    """The form answer is reported to two decimals, so nothing may truncate.

    Every other expected value in this file is a whole number, which hides
    both truncation to int and premature rounding.
    """
    _add_sample(db, "a", counts=(10, 10, 10, 10, 10))
    _add_sample(db, "b", counts=(11, 10, 10, 10, 10))
    _add_sample(db, "c", counts=(13, 10, 10, 10, 10))
    db.commit()

    result = mean_count(db, Cohort(), "b_cell")
    assert result == pytest.approx(34 / 3)
    assert result != int(result or 0)


def test_an_unknown_population_is_rejected(db: sqlite3.Connection) -> None:
    _add_sample(db, "a", counts=(10, 20, 30, 40, 50))
    db.commit()

    with pytest.raises(ValueError, match="population"):
        mean_count(db, Cohort(), "not_a_population")


def test_a_cohort_matching_nothing_returns_none(db: sqlite3.Connection) -> None:
    """None rather than a ZeroDivisionError, and rather than a misleading 0.0."""
    _add_sample(db, "a", counts=(10, 20, 30, 40, 50))
    db.commit()

    assert mean_count(db, Cohort(condition="nonexistent"), "b_cell") is None
