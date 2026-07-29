"""Tests for the Part 3 responder / non-responder comparison.

Two properties matter more than the p-values themselves.

Benjamini-Hochberg is applied across all five populations at once, so a q-value
cannot be computed for one population in isolation. That is why `compare`
returns every population from a single call.

Every subject in the real data contributes three samples, so a cohort spanning
timepoints violates the independence assumption of the test. The result reports
sample and subject counts separately and flags the divergence rather than
quietly pooling.
"""

from __future__ import annotations

import sqlite3

import pytest

from cellcount.cohort import Cohort
from cellcount.comparison import compare
from cellcount.db import create_schema
from cellcount.loader import POPULATIONS

Counts = tuple[int, int, int, int, int]

# Each tuple sums to 200, so a percentage is simply count / 2.
_BASELINE = [(10 + i, 20 + i, 30 + i, 40 + i, 100 - 4 * i) for i in range(12)]
# b_cell shifted by 20 counts, absorbed by monocyte so the total is unchanged.
_B_CELL_SHIFTED = [(30 + i, 20 + i, 30 + i, 40 + i, 80 - 4 * i) for i in range(12)]


def _seed_groups(
    conn: sqlite3.Connection,
    groups: dict[str, list[Counts]],
    *,
    samples_per_subject: int = 1,
) -> None:
    """One subject per count tuple, each with `samples_per_subject` PBMC samples."""
    conn.execute("INSERT INTO projects (project_id) VALUES ('prj1')")
    conn.executemany(
        "INSERT INTO populations (population_id, name) VALUES (?, ?)",
        list(enumerate(POPULATIONS, start=1)),
    )
    subject_number = 0
    for group, rows in groups.items():
        for counts in rows:
            subject_number += 1
            subject = f"sbj{subject_number:03d}"
            conn.execute(
                "INSERT INTO subjects "
                "(subject_id, project_id, condition, age, sex, treatment, response) "
                "VALUES (?, 'prj1', 'melanoma', 50, 'M', 'miraclib', ?)",
                (subject, group),
            )
            for visit in range(samples_per_subject):
                sample = f"{subject}-t{visit}"
                conn.execute(
                    "INSERT INTO samples (sample_id, subject_id, sample_type, "
                    "time_from_treatment_start) VALUES (?, ?, 'PBMC', ?)",
                    (sample, subject, visit * 7),
                )
                conn.executemany(
                    "INSERT INTO cell_counts (sample_id, population_id, count) "
                    "VALUES (?, ?, ?)",
                    [(sample, i + 1, counts[i]) for i in range(len(POPULATIONS))],
                )
    conn.commit()


@pytest.fixture
def no_difference(conn: sqlite3.Connection) -> sqlite3.Connection:
    create_schema(conn)
    _seed_groups(conn, {"yes": _BASELINE, "no": list(_BASELINE)})
    return conn


@pytest.fixture
def planted_difference(conn: sqlite3.Connection) -> sqlite3.Connection:
    create_schema(conn)
    _seed_groups(conn, {"yes": _BASELINE, "no": _B_CELL_SHIFTED})
    return conn


def test_reports_sample_and_subject_counts_per_group(
    no_difference: sqlite3.Connection,
) -> None:
    result = compare(no_difference, Cohort())
    assert result.n_samples == {"yes": 12, "no": 12}
    assert result.n_subjects == {"yes": 12, "no": 12}


def test_repeated_measures_is_false_with_one_sample_per_subject(
    no_difference: sqlite3.Connection,
) -> None:
    assert compare(no_difference, Cohort()).repeated_measures is False


def test_repeated_measures_is_true_when_subjects_recur(
    conn: sqlite3.Connection,
) -> None:
    create_schema(conn)
    _seed_groups(conn, {"yes": _BASELINE, "no": list(_BASELINE)}, samples_per_subject=3)
    result = compare(conn, Cohort())
    assert result.repeated_measures is True
    assert result.n_samples == {"yes": 36, "no": 36}
    assert result.n_subjects == {"yes": 12, "no": 12}


def test_restricting_to_baseline_removes_repeated_measures(
    conn: sqlite3.Connection,
) -> None:
    create_schema(conn)
    _seed_groups(conn, {"yes": _BASELINE, "no": list(_BASELINE)}, samples_per_subject=3)
    result = compare(conn, Cohort(timepoints=(0,)))
    assert result.repeated_measures is False


def test_every_population_is_reported(no_difference: sqlite3.Connection) -> None:
    result = compare(no_difference, Cohort())
    assert {p.population for p in result.populations} == set(POPULATIONS)


def test_q_values_are_at_least_p_values(planted_difference: sqlite3.Connection) -> None:
    for population in compare(planted_difference, Cohort()).populations:
        assert population.p_value is not None
        assert population.q_value is not None
        assert population.q_value >= population.p_value - 1e-12


def test_q_values_are_monotone_in_p_values(
    planted_difference: sqlite3.Connection,
) -> None:
    ordered = sorted(
        compare(planted_difference, Cohort()).populations,
        key=lambda p: p.p_value or 1.0,
    )
    q_values = [p.q_value for p in ordered if p.q_value is not None]
    assert len(q_values) == len(ordered)
    assert q_values == sorted(q_values)


def test_planted_difference_has_the_smallest_p_value(
    planted_difference: sqlite3.Connection,
) -> None:
    result = compare(planted_difference, Cohort())
    smallest = min(result.populations, key=lambda p: p.p_value or 1.0)
    assert smallest.population == "b_cell"
    assert smallest.q_value is not None
    assert smallest.q_value < 0.05


def test_identical_groups_yield_no_significant_population(
    no_difference: sqlite3.Connection,
) -> None:
    for population in compare(no_difference, Cohort()).populations:
        assert population.q_value is not None
        assert population.q_value > 0.05


def test_values_are_returned_for_plotting(no_difference: sqlite3.Connection) -> None:
    b_cell = next(
        p
        for p in compare(no_difference, Cohort()).populations
        if p.population == "b_cell"
    )
    assert len(b_cell.values["yes"]) == 12
    assert len(b_cell.values["no"]) == 12
    assert all(0.0 <= v <= 100.0 for v in b_cell.values["yes"])


def test_medians_are_reported_per_group(no_difference: sqlite3.Connection) -> None:
    b_cell = next(
        p
        for p in compare(no_difference, Cohort()).populations
        if p.population == "b_cell"
    )
    assert set(b_cell.median) == {"yes", "no"}


def test_cohort_matching_nothing_returns_an_empty_result(
    no_difference: sqlite3.Connection,
) -> None:
    result = compare(no_difference, Cohort(condition="nonexistent"))
    assert result.populations == []
    assert result.n_samples == {}
    assert result.repeated_measures is False


def test_too_few_samples_reports_counts_without_statistics(
    conn: sqlite3.Connection,
) -> None:
    """A tiny group is visible in the output rather than silently dropped."""
    create_schema(conn)
    _seed_groups(conn, {"yes": _BASELINE[:2], "no": _BASELINE[:2]})
    result = compare(conn, Cohort())
    assert result.n_samples == {"yes": 2, "no": 2}
    for population in result.populations:
        assert population.p_value is None
        assert population.q_value is None


def test_a_tied_population_does_not_break_the_whole_batch(
    conn: sqlite3.Connection,
) -> None:
    """One untestable population must not take the other four down with it.

    When every value in both groups is identical, mannwhitneyu returns nan.
    Feeding nan to false_discovery_control raises, which would discard results
    for populations that do have signal.
    """
    create_schema(conn)
    # cd8, cd4 and nk are constant across every subject in both groups.
    tied = [(10 + i, 20, 30, 40, 100 - i) for i in range(6)]
    shifted = [(40 + i, 20, 30, 40, 70 - i) for i in range(6)]
    _seed_groups(conn, {"yes": tied, "no": shifted})

    result = compare(conn, Cohort())

    assert {p.population for p in result.populations} == set(POPULATIONS)
    b_cell = next(p for p in result.populations if p.population == "b_cell")
    assert b_cell.p_value is not None
    assert b_cell.q_value is not None


def test_effect_size_is_half_when_groups_are_identical(
    no_difference: sqlite3.Connection,
) -> None:
    for population in compare(no_difference, Cohort()).populations:
        assert population.effect_size == pytest.approx(0.5)


def test_effect_size_is_oriented_by_the_first_group(
    planted_difference: sqlite3.Connection,
) -> None:
    """Groups are sorted, so for `response` the reference is 'no', not 'yes'.

    b_cell is planted higher in the 'no' group, so P(no > yes) must be 1.0.
    Getting this backwards would invert every legend in the dashboard.
    """
    result = compare(planted_difference, Cohort())
    assert result.groups == ("no", "yes")
    b_cell = next(p for p in result.populations if p.population == "b_cell")
    assert b_cell.effect_size == pytest.approx(1.0)


def test_effect_size_is_none_below_the_minimum_group_size(
    conn: sqlite3.Connection,
) -> None:
    create_schema(conn)
    _seed_groups(conn, {"yes": _BASELINE[:2], "no": _BASELINE[:2]})
    for population in compare(conn, Cohort()).populations:
        assert population.effect_size is None


def test_rejects_an_unknown_split_column(no_difference: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="split"):
        compare(no_difference, Cohort(), split_on="subjects; DROP TABLE samples")


def test_rejects_a_split_that_yields_one_group(
    no_difference: sqlite3.Connection,
) -> None:
    with pytest.raises(ValueError, match="two groups"):
        compare(no_difference, Cohort(response="yes"))


def test_null_split_values_are_excluded(conn: sqlite3.Connection) -> None:
    """Healthy controls have no response to compare; they are not a third group."""
    create_schema(conn)
    _seed_groups(conn, {"yes": _BASELINE, "no": list(_BASELINE)})
    conn.execute(
        "INSERT INTO subjects "
        "(subject_id, project_id, condition, age, sex, treatment, response) "
        "VALUES ('sbj999', 'prj1', 'melanoma', 50, 'M', 'none', NULL)"
    )
    conn.execute(
        "INSERT INTO samples (sample_id, subject_id, sample_type, "
        "time_from_treatment_start) VALUES ('sbj999-t0', 'sbj999', 'PBMC', 0)"
    )
    conn.executemany(
        "INSERT INTO cell_counts (sample_id, population_id, count) VALUES (?, ?, ?)",
        [("sbj999-t0", i + 1, 40) for i in range(len(POPULATIONS))],
    )
    conn.commit()

    result = compare(conn, Cohort())
    assert set(result.n_samples) == {"yes", "no"}
