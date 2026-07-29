"""Tests for the Part 3 responder / non-responder comparison.

Two properties matter more than the p-values themselves.

Benjamini-Hochberg is applied across every testable population at once, so a
q-value cannot be computed for one population in isolation. That is why
`compare` returns every population from a single call.

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
from cellcount.db import connect, create_schema
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
    samples_per_subject: int | dict[str, int] = 1,
) -> None:
    """One subject per count tuple, each with `samples_per_subject` PBMC samples.

    Group sizes and visit counts can differ per group, because symmetric
    fixtures cannot detect a statistic that uses the wrong group's size.
    """
    conn.execute("INSERT INTO projects (project_id) VALUES ('prj1')")
    conn.executemany(
        "INSERT INTO populations (population_id, name) VALUES (?, ?)",
        list(enumerate(POPULATIONS, start=1)),
    )
    subject_number = 0
    for group, rows in groups.items():
        visits = (
            samples_per_subject
            if isinstance(samples_per_subject, int)
            else samples_per_subject[group]
        )
        for counts in rows:
            subject_number += 1
            subject = f"sbj{subject_number:03d}"
            conn.execute(
                "INSERT INTO subjects "
                "(subject_id, project_id, condition, age, sex, treatment, response) "
                "VALUES (?, 'prj1', 'melanoma', 50, 'M', 'miraclib', ?)",
                (subject, group),
            )
            for visit in range(visits):
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


def _benjamini_hochberg(p_values: list[float]) -> list[float]:
    """BH written out longhand, so the test does not check scipy against itself.

    Walking from the largest p-value down, each adjusted value is the running
    minimum of (m / rank) * p, capped at 1.
    """
    m = len(p_values)
    ascending = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running_min = 1.0
    for offset, index in enumerate(reversed(ascending), start=1):
        rank = m - offset + 1
        running_min = min(running_min, p_values[index] * m / rank)
        adjusted[index] = min(1.0, running_min)
    return adjusted


def test_q_values_are_the_benjamini_hochberg_adjustment(
    planted_difference: sqlite3.Connection,
) -> None:
    """Pins the correction itself.

    The surrounding tests (q >= p, monotone, smallest p is significant) are all
    satisfied by q = p, so none of them would notice the correction being
    dropped or swapped for Bonferroni.
    """
    tested = [
        population
        for population in compare(planted_difference, Cohort()).populations
        if population.p_value is not None
    ]
    assert len(tested) == len(POPULATIONS)

    expected = _benjamini_hochberg([p.p_value for p in tested if p.p_value])
    for population, want in zip(tested, expected, strict=True):
        assert population.q_value == pytest.approx(want)


def test_statistics_are_reported_at_four_per_group(conn: sqlite3.Connection) -> None:
    """Sizes are literal, not derived from MIN_GROUP_SIZE.

    Deriving them would move the boundary with the constant, so the pair would
    pass at any threshold and pin nothing.
    """
    create_schema(conn)
    rows = _BASELINE[:4]
    _seed_groups(conn, {"yes": rows, "no": list(rows)})
    for population in compare(conn, Cohort()).populations:
        assert population.p_value is not None


def test_statistics_are_withheld_at_three_per_group(conn: sqlite3.Connection) -> None:
    """Three per group cannot reach alpha even uncorrected, so nothing is reported."""
    create_schema(conn)
    rows = _BASELINE[:3]
    _seed_groups(conn, {"yes": rows, "no": list(rows)})
    for population in compare(conn, Cohort()).populations:
        assert population.p_value is None


def test_the_test_is_two_sided(conn: sqlite3.Connection) -> None:
    """Mirroring which group is higher must not change the p-value.

    A one-sided alternative would report a small p in one direction and close
    to 1 in the other.
    """

    def b_cell_p(connection: sqlite3.Connection) -> float | None:
        result = compare(connection, Cohort())
        return next(p for p in result.populations if p.population == "b_cell").p_value

    create_schema(conn)
    _seed_groups(conn, {"yes": _BASELINE, "no": _B_CELL_SHIFTED})
    forward = b_cell_p(conn)

    mirrored = connect(":memory:")
    try:
        create_schema(mirrored)
        _seed_groups(mirrored, {"yes": _B_CELL_SHIFTED, "no": _BASELINE})
        backward = b_cell_p(mirrored)
    finally:
        mirrored.close()

    assert forward == pytest.approx(backward)


def test_a_population_missing_from_one_group_is_dropped_not_raised(
    conn: sqlite3.Connection,
) -> None:
    """median() over an empty list raises StatisticsError, a ValueError subclass.

    Letting that escape would make an internal gap indistinguishable from a
    caller error once the API maps ValueError to a 4xx.
    """
    create_schema(conn)
    _seed_groups(conn, {"yes": _BASELINE, "no": list(_BASELINE)})
    # Remove nk_cell from every "no" sample.
    conn.execute(
        "DELETE FROM cell_counts WHERE population_id = "
        "(SELECT population_id FROM populations WHERE name = 'nk_cell') "
        "AND sample_id IN (SELECT sample_id FROM samples JOIN subjects "
        "USING (subject_id) WHERE response = 'no')"
    )
    conn.commit()

    result = compare(conn, Cohort())
    reported = {p.population for p in result.populations}
    assert "nk_cell" not in reported
    assert reported == set(POPULATIONS) - {"nk_cell"}


# b_cell percentages 1, 2, 8 and 40 over a total of 1000: median 5, mean 12.75.
_SKEWED: list[Counts] = [
    (10, 100, 100, 100, 690),
    (20, 100, 100, 100, 680),
    (80, 100, 100, 100, 620),
    (400, 100, 100, 100, 300),
]

# A flat 5% b_cell. Against _SKEWED the pairwise differences are -4, -3, +3
# and +35, whose median is 0 but whose mean is 7.75.
_FLAT: list[Counts] = [(50, 100, 100, 100, 650)] * 4


def test_effect_size_uses_both_group_sizes(conn: sqlite3.Connection) -> None:
    """The denominator is n_left * n_right, not n_left squared.

    Equal-sized fixtures cannot tell the two apart, and the real cohort is
    325 against 331. With unequal groups the wrong denominator produces
    values outside [0, 1], which is not a probability.
    """
    create_schema(conn)
    # Groups sort to ("no", "yes"), so "no" is the reference. Give it the
    # higher values and complete separation, which must yield exactly 1.0.
    _seed_groups(conn, {"no": _B_CELL_SHIFTED[:12], "yes": _BASELINE[:4]})

    result = compare(conn, Cohort())
    assert result.n_samples == {"no": 12, "yes": 4}
    b_cell = next(p for p in result.populations if p.population == "b_cell")
    assert b_cell.effect_size == pytest.approx(1.0)


def test_the_group_size_gate_uses_the_smaller_group(
    conn: sqlite3.Connection,
) -> None:
    """One group below the minimum withholds statistics, however large the other."""
    create_schema(conn)
    _seed_groups(conn, {"no": _BASELINE[:12], "yes": _BASELINE[:2]})

    for population in compare(conn, Cohort()).populations:
        assert population.p_value is None
        assert population.effect_size is None


def test_medians_are_medians_not_means(conn: sqlite3.Connection) -> None:
    """A skewed fixture, because on symmetric data the two coincide."""
    create_schema(conn)
    _seed_groups(conn, {"yes": _SKEWED, "no": list(_SKEWED)})

    b_cell = next(
        p for p in compare(conn, Cohort()).populations if p.population == "b_cell"
    )
    assert b_cell.median["yes"] == pytest.approx(5.0)
    assert b_cell.median["no"] == pytest.approx(5.0)


def test_n_counts_observations_of_that_population(
    conn: sqlite3.Connection,
) -> None:
    """`n` is per population, which can be fewer than the group's sample count."""
    create_schema(conn)
    _seed_groups(conn, {"yes": _BASELINE, "no": list(_BASELINE)})
    conn.execute(
        "DELETE FROM cell_counts WHERE population_id = "
        "(SELECT population_id FROM populations WHERE name = 'nk_cell') "
        "AND sample_id IN (SELECT sample_id FROM samples JOIN subjects "
        "USING (subject_id) WHERE response = 'yes' LIMIT 3)"
    )
    conn.commit()

    result = compare(conn, Cohort())
    assert result.n_samples["yes"] == 12
    nk_cell = next(p for p in result.populations if p.population == "nk_cell")
    assert nk_cell.n["yes"] == 9
    assert nk_cell.n["no"] == 12


def test_repeated_measures_is_true_when_only_one_group_repeats(
    conn: sqlite3.Connection,
) -> None:
    """`any`, not `all`. One arm with repeat visits already breaks independence."""
    create_schema(conn)
    _seed_groups(
        conn,
        {"yes": _BASELINE, "no": list(_BASELINE)},
        samples_per_subject={"yes": 3, "no": 1},
    )

    result = compare(conn, Cohort())
    assert result.repeated_measures is True
    assert result.n_samples == {"yes": 36, "no": 12}
    assert result.n_subjects == {"yes": 12, "no": 12}


def test_shift_and_interval_are_reported(
    planted_difference: sqlite3.Connection,
) -> None:
    """A null result needs a bound, not just a p-value.

    The shift is the Hodges-Lehmann estimate, the median of all pairwise
    differences, which is the location estimate Mann-Whitney actually tests.
    """
    b_cell = next(
        p
        for p in compare(planted_difference, Cohort()).populations
        if p.population == "b_cell"
    )
    assert b_cell.shift is not None
    assert b_cell.shift_ci is not None
    low, high = b_cell.shift_ci
    assert low <= b_cell.shift <= high


def test_shift_is_oriented_like_the_effect_size(
    planted_difference: sqlite3.Connection,
) -> None:
    """Positive means the first group is higher, matching effect_size > 0.5."""
    result = compare(planted_difference, Cohort())
    assert result.groups == ("no", "yes")  # b_cell is planted higher in "no"
    b_cell = next(p for p in result.populations if p.population == "b_cell")
    assert b_cell.shift is not None
    assert b_cell.shift > 0
    assert b_cell.effect_size is not None
    assert b_cell.effect_size > 0.5


def test_an_interval_covering_zero_accompanies_a_null_result(
    no_difference: sqlite3.Connection,
) -> None:
    """This is what makes a null a bounded negative rather than an absence."""
    for population in compare(no_difference, Cohort()).populations:
        assert population.shift_ci is not None
        low, high = population.shift_ci
        assert low <= 0.0 <= high


def test_shift_is_withheld_below_the_minimum_group_size(
    conn: sqlite3.Connection,
) -> None:
    create_schema(conn)
    _seed_groups(conn, {"yes": _BASELINE[:2], "no": _BASELINE[:2]})
    for population in compare(conn, Cohort()).populations:
        assert population.shift is None
        assert population.shift_ci is None


def test_shift_is_a_median_of_differences_not_a_mean(
    conn: sqlite3.Connection,
) -> None:
    """Symmetric fixtures cannot tell these apart, so this one is skewed.

    Differences are -4, -3, +3, +35 percentage points: median 0, mean 7.75.
    """
    create_schema(conn)
    _seed_groups(conn, {"no": _SKEWED, "yes": _FLAT})

    b_cell = next(
        p for p in compare(conn, Cohort()).populations if p.population == "b_cell"
    )
    assert b_cell.shift == pytest.approx(0.0)


def test_the_interval_is_narrower_than_the_full_range_of_differences(
    planted_difference: sqlite3.Connection,
) -> None:
    """A 95% interval must trim the extremes.

    Returning the smallest and largest pairwise difference would satisfy every
    other assertion about the interval while being a 100% interval.
    """
    b_cell = next(
        p
        for p in compare(planted_difference, Cohort()).populations
        if p.population == "b_cell"
    )
    assert b_cell.shift_ci is not None
    differences = sorted(
        x - y for x in b_cell.values["no"] for y in b_cell.values["yes"]
    )
    low, high = b_cell.shift_ci
    assert low > differences[0]
    assert high < differences[-1]


def test_the_interval_has_positive_width(
    no_difference: sqlite3.Connection,
) -> None:
    """A collapsed interval would satisfy every containment assertion above."""
    for population in compare(no_difference, Cohort()).populations:
        assert population.shift_ci is not None
        low, high = population.shift_ci
        assert high > low


def test_a_looser_confidence_level_gives_a_narrower_interval(
    planted_difference: sqlite3.Connection,
) -> None:
    """Pins that alpha actually reaches the interval rather than being ignored."""

    def width(alpha: float) -> float:
        result = compare(planted_difference, Cohort(), alpha=alpha)
        b_cell = next(p for p in result.populations if p.population == "b_cell")
        assert b_cell.shift_ci is not None
        low, high = b_cell.shift_ci
        return high - low

    assert width(0.20) < width(0.01)


def test_n_tested_reports_how_many_entered_the_correction(
    no_difference: sqlite3.Connection,
) -> None:
    """The q-values mean nothing without knowing how many tests they span."""
    assert compare(no_difference, Cohort()).n_tested == len(POPULATIONS)


def test_n_tested_excludes_untestable_populations(conn: sqlite3.Connection) -> None:
    create_schema(conn)
    tied = [(10 + i, 20, 30, 40, 100 - i) for i in range(6)]
    shifted = [(40 + i, 20, 30, 40, 70 - i) for i in range(6)]
    _seed_groups(conn, {"yes": tied, "no": shifted})

    result = compare(conn, Cohort())
    assert result.n_tested < len(POPULATIONS)
    assert result.n_tested == sum(
        1 for p in result.populations if p.p_value is not None
    )


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
