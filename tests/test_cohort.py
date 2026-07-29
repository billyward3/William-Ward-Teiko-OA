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


def test_clause_order_is_deterministic() -> None:
    """Stable SQL text lets SQLite reuse a prepared statement across calls."""
    first, _ = where_clause(Cohort(sex="M", condition="melanoma"))
    second, _ = where_clause(Cohort(condition="melanoma", sex="M"))
    assert first == second


def test_cohort_is_hashable() -> None:
    """Frozen and hashable, so results can be cached per cohort later."""
    assert hash(Cohort(condition="melanoma")) == hash(Cohort(condition="melanoma"))
    assert Cohort(condition="melanoma") != Cohort(condition="carcinoma")
