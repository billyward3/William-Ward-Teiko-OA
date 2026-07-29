"""Tests for the Part 2 summary table.

The spec fixes the output columns exactly: sample, total_count, population,
count, percentage. One row per sample and population.

The seeded fixture gives every sample a total of 200 cells, so expected
percentages are just count / 2 and can be written down rather than recomputed.
"""

from __future__ import annotations

import sqlite3

import pytest

from cellcount.cohort import Cohort
from cellcount.db import create_schema
from cellcount.loader import POPULATIONS
from cellcount.summary import summary_rows

SPEC_COLUMNS = ["sample", "total_count", "population", "count", "percentage"]


def test_returns_one_row_per_sample_and_population(
    seeded_db: sqlite3.Connection,
) -> None:
    rows = summary_rows(seeded_db)
    assert len(rows) == 4 * 5  # four samples, five populations


def test_row_fields_match_the_spec_columns(seeded_db: sqlite3.Connection) -> None:
    row = summary_rows(seeded_db)[0]
    assert list(vars(row)) == SPEC_COLUMNS


def test_total_count_is_that_samples_own_sum(
    seeded_db: sqlite3.Connection, sample_totals: dict[str, int]
) -> None:
    """Each sample must be divided by its own total, not a shared constant."""
    for row in summary_rows(seeded_db):
        assert row.total_count == sample_totals[row.sample]


def test_percentages_sum_to_100_for_every_sample(
    seeded_db: sqlite3.Connection,
) -> None:
    """Approximate, because a total of 300 gives percentages that repeat in binary."""
    totals: dict[str, float] = {}
    for row in summary_rows(seeded_db):
        totals[row.sample] = totals.get(row.sample, 0.0) + row.percentage
    for sample, total in totals.items():
        assert total == pytest.approx(100.0), f"{sample} sums to {total}"


def test_percentage_is_count_over_total(seeded_db: sqlite3.Connection) -> None:
    rows = {(r.sample, r.population): r for r in summary_rows(seeded_db)}
    # s1 counts are (10, 20, 30, 40, 100) over a total of 200.
    assert rows[("s1", "b_cell")].percentage == 5.0
    assert rows[("s1", "cd8_t_cell")].percentage == 10.0
    assert rows[("s1", "cd4_t_cell")].percentage == 15.0
    assert rows[("s1", "nk_cell")].percentage == 20.0
    assert rows[("s1", "monocyte")].percentage == 50.0


def test_unfiltered_call_returns_every_sample(seeded_db: sqlite3.Connection) -> None:
    samples = {row.sample for row in summary_rows(seeded_db)}
    assert samples == {"s1", "s2", "s3", "s4"}


def test_cohort_narrows_by_sample_type(seeded_db: sqlite3.Connection) -> None:
    rows = summary_rows(seeded_db, Cohort(sample_type="WB"))
    assert {row.sample for row in rows} == {"s4"}


def test_cohort_narrows_by_subject_attribute(seeded_db: sqlite3.Connection) -> None:
    rows = summary_rows(seeded_db, Cohort(condition="carcinoma"))
    assert {row.sample for row in rows} == {"s4"}


def test_cohort_narrows_by_timepoint(seeded_db: sqlite3.Connection) -> None:
    rows = summary_rows(seeded_db, Cohort(timepoints=(7,)))
    assert {row.sample for row in rows} == {"s2"}


def test_cohort_fields_combine(seeded_db: sqlite3.Connection) -> None:
    rows = summary_rows(
        seeded_db, Cohort(condition="melanoma", sample_type="PBMC", timepoints=(0,))
    )
    assert {row.sample for row in rows} == {"s1", "s3"}


def test_cohort_matching_nothing_returns_empty(seeded_db: sqlite3.Connection) -> None:
    assert summary_rows(seeded_db, Cohort(condition="nonexistent")) == []


def test_zero_total_sample_yields_a_number_not_null(
    conn: sqlite3.Connection,
) -> None:
    """A sample with no cells at all must not produce NULL percentages.

    SQLite returns NULL for division by zero. That would violate SummaryRow's
    declared float type and break `statistics.median` downstream, and mypy
    cannot catch it because sqlite3 hands back Any.
    """
    create_schema(conn)
    with conn:
        conn.executemany(
            "INSERT INTO populations (population_id, name) VALUES (?, ?)",
            list(enumerate(POPULATIONS, start=1)),
        )
        conn.execute("INSERT INTO projects (project_id) VALUES ('prj1')")
        conn.execute(
            "INSERT INTO subjects "
            "(subject_id, project_id, condition, age, sex, treatment, response) "
            "VALUES ('sbjZ', 'prj1', 'melanoma', 50, 'M', 'miraclib', 'yes')"
        )
        conn.execute(
            "INSERT INTO samples (sample_id, subject_id, sample_type, "
            "time_from_treatment_start) VALUES ('sZ', 'sbjZ', 'PBMC', 0)"
        )
        conn.executemany(
            "INSERT INTO cell_counts (sample_id, population_id, count) "
            "VALUES (?, ?, ?)",
            [("sZ", i + 1, 0) for i in range(len(POPULATIONS))],
        )

    rows = summary_rows(conn)
    assert len(rows) == len(POPULATIONS)
    for row in rows:
        assert row.percentage is not None
        assert isinstance(row.percentage, float)
        assert row.percentage == 0.0


def test_rows_are_ordered_deterministically(seeded_db: sqlite3.Connection) -> None:
    first = summary_rows(seeded_db)
    second = summary_rows(seeded_db)
    assert first == second
    assert [r.sample for r in first] == sorted(r.sample for r in first)
