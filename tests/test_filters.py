"""Tests for the filter options a dashboard populates its dropdowns from.

Cohort filters are exact-match and case-sensitive, so `condition = "Melanoma"`
selects nothing at all. A dashboard that lets a user type the value is therefore
a dashboard that silently returns empty tables. These options exist so the
choice is made from the values the database actually holds.

Two shapes matter here and neither is visible in a well-behaved fixture:
a column that is NULL for some rows (`response` is, for untreated controls),
and timepoints where numeric and lexicographic order disagree (0, 7, 14).
"""

from __future__ import annotations

import sqlite3

from cellcount.cohort import FILTER_COLUMNS
from cellcount.db import create_schema
from cellcount.filters import filter_options
from cellcount.loader import POPULATIONS


def _add_untreated_subject(conn: sqlite3.Connection) -> None:
    """A healthy control: no treatment and no response, both stored as NULL.

    NULL is not a value a user can select, so it must not reach the dropdown.
    """
    with conn:
        conn.execute(
            "INSERT INTO subjects "
            "(subject_id, project_id, condition, age, sex, treatment, response) "
            "VALUES ('sbj9', 'prj2', 'healthy', 30, 'F', NULL, NULL)"
        )
        conn.execute(
            "INSERT INTO samples "
            "(sample_id, subject_id, sample_type, time_from_treatment_start) "
            "VALUES ('s9', 'sbj9', 'PBMC', 14)"
        )


def test_every_cohort_field_gets_options(seeded_db: sqlite3.Connection) -> None:
    """Keyed by cohort field name, so the client maps a key onto a query parameter."""
    options = filter_options(seeded_db)
    assert list(options.fields) == list(FILTER_COLUMNS)


def test_options_are_the_distinct_values_present(
    seeded_db: sqlite3.Connection,
) -> None:
    options = filter_options(seeded_db)
    # Two of the three subjects are melanoma, so a query that did not collapse
    # duplicates would offer it twice.
    assert options.fields["condition"] == ["carcinoma", "melanoma"]
    assert options.fields["treatment"] == ["miraclib", "phauximab"]
    assert options.fields["response"] == ["no", "yes"]
    assert options.fields["sex"] == ["F", "M"]
    assert options.fields["sample_type"] == ["PBMC", "WB"]


def test_null_is_not_offered_as_a_choice(seeded_db: sqlite3.Connection) -> None:
    """A NULL response means "not applicable", not a group a user can pick."""
    _add_untreated_subject(seeded_db)
    options = filter_options(seeded_db)
    assert options.fields["response"] == ["no", "yes"]
    assert options.fields["treatment"] == ["miraclib", "phauximab"]
    assert None not in options.fields["response"]


def test_timepoints_are_integers_in_numeric_order(
    seeded_db: sqlite3.Connection,
) -> None:
    """0, 7, 14 sort differently as text than as numbers, so the order is a claim."""
    _add_untreated_subject(seeded_db)
    options = filter_options(seeded_db)
    assert options.timepoints == [0, 7, 14]


def test_populations_come_from_the_dimension_table(
    seeded_db: sqlite3.Connection,
) -> None:
    options = filter_options(seeded_db)
    assert options.populations == sorted(POPULATIONS)


def test_an_empty_database_yields_empty_options(conn: sqlite3.Connection) -> None:
    """No rows is not an error: it is what a database says before the load runs."""
    create_schema(conn)
    options = filter_options(conn)
    assert options.fields == {field: [] for field in FILTER_COLUMNS}
    assert options.timepoints == []
    assert options.populations == []
