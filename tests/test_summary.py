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
from cellcount.summary import summary_page

SPEC_COLUMNS = ["sample", "total_count", "population", "count", "percentage"]


def test_returns_one_row_per_sample_and_population(
    seeded_db: sqlite3.Connection,
) -> None:
    rows = summary_page(seeded_db).rows
    assert len(rows) == 4 * 5  # four samples, five populations


def test_row_fields_match_the_spec_columns(seeded_db: sqlite3.Connection) -> None:
    row = summary_page(seeded_db).rows[0]
    assert list(vars(row)) == SPEC_COLUMNS


def test_total_count_is_that_samples_own_sum(
    seeded_db: sqlite3.Connection, sample_totals: dict[str, int]
) -> None:
    """Each sample must be divided by its own total, not a shared constant."""
    for row in summary_page(seeded_db).rows:
        assert row.total_count == sample_totals[row.sample]


def test_percentages_sum_to_100_for_every_sample(
    seeded_db: sqlite3.Connection,
) -> None:
    """Approximate, because a total of 300 gives percentages that repeat in binary."""
    totals: dict[str, float] = {}
    for row in summary_page(seeded_db).rows:
        totals[row.sample] = totals.get(row.sample, 0.0) + row.percentage
    for sample, total in totals.items():
        assert total == pytest.approx(100.0), f"{sample} sums to {total}"


def test_percentage_is_count_over_total(seeded_db: sqlite3.Connection) -> None:
    rows = {(r.sample, r.population): r for r in summary_page(seeded_db).rows}
    # s1 counts are (10, 20, 30, 40, 100) over a total of 200.
    assert rows[("s1", "b_cell")].percentage == 5.0
    assert rows[("s1", "cd8_t_cell")].percentage == 10.0
    assert rows[("s1", "cd4_t_cell")].percentage == 15.0
    assert rows[("s1", "nk_cell")].percentage == 20.0
    assert rows[("s1", "monocyte")].percentage == 50.0


def test_unfiltered_call_returns_every_sample(seeded_db: sqlite3.Connection) -> None:
    samples = {row.sample for row in summary_page(seeded_db).rows}
    assert samples == {"s1", "s2", "s3", "s4"}


def test_cohort_narrows_by_sample_type(seeded_db: sqlite3.Connection) -> None:
    rows = summary_page(seeded_db, Cohort(sample_type="WB")).rows
    assert {row.sample for row in rows} == {"s4"}


def test_cohort_narrows_by_subject_attribute(seeded_db: sqlite3.Connection) -> None:
    rows = summary_page(seeded_db, Cohort(condition="carcinoma")).rows
    assert {row.sample for row in rows} == {"s4"}


def test_cohort_narrows_by_timepoint(seeded_db: sqlite3.Connection) -> None:
    rows = summary_page(seeded_db, Cohort(timepoints=(7,))).rows
    assert {row.sample for row in rows} == {"s2"}


def test_cohort_fields_combine(seeded_db: sqlite3.Connection) -> None:
    rows = summary_page(
        seeded_db,
        Cohort(condition="melanoma", sample_type="PBMC", timepoints=(0,)),
    ).rows
    assert {row.sample for row in rows} == {"s1", "s3"}


def test_cohort_matching_nothing_returns_empty(seeded_db: sqlite3.Connection) -> None:
    page = summary_page(seeded_db, Cohort(condition="nonexistent"))
    assert page.rows == []
    assert page.total == 0


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

    rows = summary_page(conn).rows
    assert len(rows) == len(POPULATIONS)
    for row in rows:
        assert row.percentage is not None
        assert isinstance(row.percentage, float)
        assert row.percentage == 0.0


def test_a_limit_caps_the_number_of_rows(seeded_db: sqlite3.Connection) -> None:
    """The unfiltered table is 52,500 rows, which no client should receive whole."""
    page = summary_page(seeded_db, limit=7)
    assert len(page.rows) == 7


def test_the_total_is_the_unpaginated_count(seeded_db: sqlite3.Connection) -> None:
    """Without it a client cannot know how many pages exist."""
    page = summary_page(seeded_db, limit=7)
    assert page.total == 4 * 5


def test_an_offset_skips_from_the_same_ordering(
    seeded_db: sqlite3.Connection,
) -> None:
    everything = summary_page(seeded_db).rows
    assert summary_page(seeded_db, limit=3, offset=5).rows == everything[5:8]


def test_paging_through_covers_every_row_exactly_once(
    seeded_db: sqlite3.Connection,
) -> None:
    collected = []
    offset = 0
    while True:
        page = summary_page(seeded_db, limit=6, offset=offset)
        if not page.rows:
            break
        collected.extend(page.rows)
        offset += 6
    assert collected == summary_page(seeded_db).rows


def test_an_offset_past_the_end_returns_no_rows_but_a_real_total(
    seeded_db: sqlite3.Connection,
) -> None:
    page = summary_page(seeded_db, offset=9999)
    assert page.rows == []
    assert page.total == 4 * 5


def test_the_total_respects_the_cohort(seeded_db: sqlite3.Connection) -> None:
    """The count must match the filter, not the whole table."""
    page = summary_page(seeded_db, Cohort(sample_type="WB"), limit=2)
    assert page.total == 5  # one sample, five populations
    assert len(page.rows) == 2


def test_a_negative_limit_is_rejected(seeded_db: sqlite3.Connection) -> None:
    """SQLite reads a negative LIMIT as unbounded, so this would return everything."""
    with pytest.raises(ValueError, match="limit"):
        summary_page(seeded_db, limit=-1)


def test_a_negative_offset_is_rejected(seeded_db: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="offset"):
        summary_page(seeded_db, offset=-5)


def test_a_zero_limit_returns_no_rows_but_a_real_total(
    seeded_db: sqlite3.Connection,
) -> None:
    page = summary_page(seeded_db, limit=0)
    assert page.rows == []
    assert page.total == 4 * 5


def test_an_offset_without_a_limit_skips_from_the_start(
    seeded_db: sqlite3.Connection,
) -> None:
    """Exercises the branch that supplies LIMIT -1 so OFFSET is legal SQL."""
    everything = summary_page(seeded_db).rows
    assert summary_page(seeded_db, offset=4).rows == everything[4:]


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

    rows = summary_page(conn).rows
    assert [r.sample for r in rows] == sorted(r.sample for r in rows)
    per_sample = [r.population for r in rows if r.sample == "sA"]
    assert per_sample == sorted(per_sample)


def test_repeated_calls_return_the_same_rows(seeded_db: sqlite3.Connection) -> None:
    assert summary_page(seeded_db).rows == summary_page(seeded_db).rows
