"""Tests for cohort filtering.

A cohort is the shared vocabulary for "which samples are we looking at". It has
three representations: these dataclass fields, a SQL WHERE clause, and (later)
API query parameters. These tests pin the translation to SQL.

Cohort values arrive from user input over HTTP, so the builder must bind every
value rather than interpolate it. That is a security property, not a style
preference, and it is tested as one.
"""

from __future__ import annotations

from cellcount.cohort import (
    ALL_SAMPLES,
    Cohort,
    conditions,
    render_where,
    where_clause,
)


def test_conditions_returns_fragments_without_the_where_keyword() -> None:
    fragments, params = conditions(Cohort(condition="melanoma", sex="M"))
    assert fragments == ["subjects.condition = ?", "subjects.sex = ?"]
    assert params == ["melanoma", "M"]


def test_conditions_of_an_unconstrained_cohort_are_empty() -> None:
    assert conditions(ALL_SAMPLES) == ([], [])


def test_render_where_joins_with_and() -> None:
    assert render_where(["a = ?", "b = ?"]) == "WHERE a = ? AND b = ?"


def test_render_where_of_nothing_is_an_empty_string() -> None:
    assert render_where([]) == ""


def test_a_caller_can_append_its_own_condition() -> None:
    """`compare` needs an IS NOT NULL alongside the cohort's own filters.

    Appending to the list beats string surgery on an already-rendered clause,
    which is what forced every caller to know the WHERE-prefix convention.
    """
    fragments, params = conditions(Cohort(condition="melanoma"))
    fragments.append("subjects.response IS NOT NULL")
    assert render_where(fragments) == (
        "WHERE subjects.condition = ? AND subjects.response IS NOT NULL"
    )
    assert params == ["melanoma"]


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
