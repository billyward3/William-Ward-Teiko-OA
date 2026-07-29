"""Tests for the Part 2 summary table.

The spec fixes the output columns exactly: sample, total_count, population,
count, percentage. One row per sample and population.

Fixture totals deliberately differ between samples (see `conftest.py`), so a
view dividing every count by a shared constant, or by another sample's total,
fails here rather than passing by coincidence.
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


def test_rows_are_sorted_regardless_of_insertion_order(
    conn: sqlite3.Connection,
) -> None:
    """Samples are inserted in reverse, so a missing ORDER BY would show.

    The main fixture inserts in sorted order, which SQLite happens to return in
    rowid order, so it cannot detect the clause being dropped.
    """
    create_schema(conn)
    with conn:
        conn.executemany(
            "INSERT INTO populations (population_id, name) VALUES (?, ?)",
            list(enumerate(POPULATIONS, start=1)),
        )
        conn.execute("INSERT INTO projects (project_id) VALUES ('prj1')")
        for sample in ("sZ", "sM", "sA"):  # deliberately not alphabetical
            subject = f"sbj-{sample}"
            conn.execute(
                "INSERT INTO subjects "
                "(subject_id, project_id, condition, age, sex, treatment, response) "
                "VALUES (?, 'prj1', 'melanoma', 50, 'M', 'miraclib', 'yes')",
                (subject,),
            )
            conn.execute(
                "INSERT INTO samples (sample_id, subject_id, sample_type, "
                "time_from_treatment_start) VALUES (?, ?, 'PBMC', 0)",
                (sample, subject),
            )
            conn.executemany(
                "INSERT INTO cell_counts (sample_id, population_id, count) "
                "VALUES (?, ?, ?)",
                [(sample, i + 1, 40) for i in range(len(POPULATIONS))],
            )

    rows = summary_rows(conn)
    assert [r.sample for r in rows] == sorted(r.sample for r in rows)
    per_sample = [r.population for r in rows if r.sample == "sA"]
    assert per_sample == sorted(per_sample)


def test_repeated_calls_return_the_same_rows(seeded_db: sqlite3.Connection) -> None:
    assert summary_rows(seeded_db) == summary_rows(seeded_db)
