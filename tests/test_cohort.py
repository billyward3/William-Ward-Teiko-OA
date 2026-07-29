"""Tests for cohort filtering.

A cohort is the shared vocabulary for "which samples are we looking at". It has
three representations: these dataclass fields, a SQL WHERE clause, and (later)
API query parameters. These tests pin the translation to SQL.

Cohort values arrive from user input over HTTP, so the builder must bind every
value rather than interpolate it. That is a security property, not a style
preference, and it is tested as one.
"""

from __future__ import annotations

from cellcount.cohort import Cohort, where_clause


def test_empty_cohort_produces_no_clause() -> None:
    clause, params = where_clause(Cohort())
    assert clause == ""
    assert params == []


def test_single_field_produces_one_condition() -> None:
    clause, params = where_clause(Cohort(condition="melanoma"))
    assert clause == "WHERE subjects.condition = ?"
    assert params == ["melanoma"]


def test_subject_and_sample_fields_reference_their_own_tables() -> None:
    clause, params = where_clause(Cohort(sex="M", sample_type="PBMC"))
    assert "subjects.sex = ?" in clause
    assert "samples.sample_type = ?" in clause
    assert params == ["M", "PBMC"]


def test_multiple_fields_combine_with_and() -> None:
    clause, _ = where_clause(
        Cohort(condition="melanoma", treatment="miraclib", sample_type="PBMC")
    )
    assert clause.count(" AND ") == 2
    assert clause.startswith("WHERE ")


def test_timepoints_become_an_in_clause() -> None:
    clause, params = where_clause(Cohort(timepoints=(0, 7)))
    assert clause == "WHERE samples.time_from_treatment_start IN (?, ?)"
    assert params == [0, 7]


def test_single_timepoint_still_uses_in() -> None:
    clause, params = where_clause(Cohort(timepoints=(0,)))
    assert clause == "WHERE samples.time_from_treatment_start IN (?)"
    assert params == [0]


def test_empty_timepoints_is_not_a_filter() -> None:
    """An empty tuple means "no constraint", not "match nothing"."""
    clause, params = where_clause(Cohort(timepoints=()))
    assert clause == ""
    assert params == []


def test_values_are_bound_never_interpolated() -> None:
    clause, params = where_clause(Cohort(condition="melanoma", sex="M"))
    assert "melanoma" not in clause
    assert "'M'" not in clause
    assert clause.count("?") == 2
    assert params == ["melanoma", "M"]


def test_sql_syntax_in_a_value_stays_a_value() -> None:
    hostile = "melanoma'; DROP TABLE samples; --"
    clause, params = where_clause(Cohort(condition=hostile))
    assert clause == "WHERE subjects.condition = ?"
    assert params == [hostile]
    assert "DROP" not in clause


def test_clause_order_follows_the_column_mapping() -> None:
    """Pins the emitted order, so reordering FILTER_COLUMNS fails here.

    Comparing two Cohorts built with the same keywords would prove nothing:
    they are the same dataclass value regardless of argument order. The literal
    string is what makes the statement text stable enough for SQLite to reuse a
    prepared statement.
    """
    clause, params = where_clause(
        Cohort(
            condition="melanoma",
            treatment="miraclib",
            response="yes",
            sex="M",
            sample_type="PBMC",
        )
    )
    assert clause == (
        "WHERE subjects.condition = ? "
        "AND subjects.treatment = ? "
        "AND subjects.response = ? "
        "AND subjects.sex = ? "
        "AND samples.sample_type = ?"
    )
    assert params == ["melanoma", "miraclib", "yes", "M", "PBMC"]
