"""Part 3: comparing population frequencies between two groups.

Three decisions are encoded here rather than left to the caller.

**Mann-Whitney U** rather than a t-test. Relative frequencies are bounded on
[0, 100] and need not be normally distributed, and a rank test assumes neither.
Note it tests stochastic dominance, so it is a test of medians only when the two
distributions share a shape.

**Benjamini-Hochberg across every population that could be tested.** Five tests
at alpha = 0.05 carry roughly a 23% chance of at least one false positive.
Controlling the false discovery rate is the right choice for screening, and it is
why every population is computed in one call: a q-value depends on the whole set
of p-values.

The set is usually all five, but a population that is entirely tied, or absent
from one group, is excluded from the correction rather than entered at p = 1.
That makes the remaining q-values slightly less conservative, which is the right
trade because a population with no variance carries no power. The number of tests
the correction ran over should be reported alongside the results.

**Two intervals per population, at two levels.** `shift_ci` covers one
population at `alpha`. `simultaneous_ci` covers the whole family at `alpha`, by
computing each interval at `alpha / n_tested`. A reader who takes five marginal
95% intervals and says "no population shifts by more than the widest of these"
has made a joint claim the marginal level does not support, so both are supplied
and the caller is expected to say which one it is quoting.

**Independence is reported, not assumed.** Each subject in the real data has
three samples, so a cohort spanning timepoints pools correlated observations and
inflates the effective sample size. `n_samples`, `n_subjects`, and
`repeated_measures` make that visible to whoever reads the result.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import NormalDist, median

import numpy as np
import numpy.typing as npt
from scipy.stats import false_discovery_control, mannwhitneyu

from cellcount.cohort import (
    ALL_SAMPLES,
    FILTER_COLUMNS,
    Cohort,
    conditions,
    render_where,
)

# Smallest group a rank test is reported for. At three per group the smallest
# achievable two-sided p is 0.100, so no result could clear alpha even before
# correction; four gives 0.029. Below the threshold, counts and distributions are
# still returned, but the statistics are None rather than a misleading number.
#
# Note this counts samples. A cohort spanning timepoints can clear it on
# pseudo-replicates from a single subject, which `repeated_measures` flags.
MIN_GROUP_SIZE = 4

# Columns a comparison may split on. Reuses the cohort's filter vocabulary, so a
# new filter becomes splittable automatically instead of needing a second edit.
# It doubles as an allowlist: `split_on` arrives from HTTP query parameters and
# is the one value interpolated into SQL rather than bound.
_SPLIT_COLUMNS = FILTER_COLUMNS

# Display only. `"yes"` and `"no"` are the values the response column stores;
# nothing keys off these strings. Kept here rather than in each renderer so the
# figure and the write-up cannot disagree about what a group is called.
GROUP_LABELS = {"no": "non-responder", "yes": "responder"}


def group_label(group: str) -> str:
    """A readable name for a split value, falling back to the value itself."""
    return GROUP_LABELS.get(group, group)


class ComparisonError(ValueError):
    """A comparison could not be produced.

    Subclasses ValueError so existing callers keep working, but the two reasons
    below are distinguishable: one is a bug, the other is a bad request, and an
    API mapping both to the same status would hide the bug behind a 4xx.
    """


class UnknownSplitColumn(ComparisonError):
    """`split_on` is not a column that can be split on. A programmer error."""


class NotTwoGroups(ComparisonError):
    """The cohort is legal but does not yield exactly two groups to compare."""


@dataclass(frozen=True)
class PopulationComparison:
    population: str
    n: dict[str, int]
    median: dict[str, float]
    values: dict[str, list[float]]
    p_value: float | None
    q_value: float | None
    shift: float | None
    """Hodges-Lehmann estimate: the median of all pairwise differences.

    In percentage points, oriented like `effect_size`, so positive means
    `groups[0]` is higher. This is the location shift Mann-Whitney actually
    tests, which makes it the right companion to its p-value.
    """
    shift_ci: tuple[float, float] | None
    """Confidence interval for `shift` at `alpha`, from the Mann-Whitney inversion.

    This is what turns a null result into a bounded one. A p-value above the
    threshold says a difference was not detected; an interval says how large a
    difference the data can rule out.

    It is an interval for this population alone, at `alpha`, while significance
    is judged by `q_value`, which is adjusted across every tested population.
    The two can therefore disagree: an interval excluding zero alongside a
    q-value above alpha is expected, not a contradiction, and happens in about
    7% of population-results across the cohorts in this dataset. Anything
    rendering both together should say which one governs.
    """
    simultaneous_ci: tuple[float, float] | None
    """The same interval widened so that the whole family holds jointly at `alpha`.

    `shift_ci` is marginal: it covers this population and no other. A statement
    quantified over populations ("no population shifts by more than x") is a
    joint claim, and a family of marginal intervals at `alpha` can hold jointly
    with probability as low as 1 - n_tested * alpha. This one is computed at
    `simultaneous_alpha`, which restores the family's level by Bonferroni and
    assumes nothing about how the populations depend on one another.

    Quote this one for a claim about every population at once, and `shift_ci`
    for a claim about one.
    """
    effect_size: float | None
    """P(x > y) + 0.5 * P(x = y), for x drawn from `groups[0]` and y from `groups[1]`.

    Groups are sorted, so for `split_on="response"` the reference is "no": a
    value above 0.5 means non-responders are higher. 0.5 means no separation.

    Reported beside the p-value because a difference can be statistically
    detectable and still far too small to act on.
    """


@dataclass(frozen=True)
class ComparisonResult:
    cohort: Cohort
    split_on: str
    groups: tuple[str, ...]
    n_samples: dict[str, int]
    n_subjects: dict[str, int]
    repeated_measures: bool
    n_tested: int
    """How many populations entered the multiple-comparison correction.

    A q-value is meaningless without it, and it is not always the full five:
    a population that is entirely tied, or absent from one group, is excluded.
    """
    alpha: float
    populations: list[PopulationComparison]


def simultaneous_alpha(alpha: float, n_tested: int) -> float:
    """The per-interval level at which `n_tested` intervals hold jointly at `alpha`.

    Bonferroni. Defined here rather than inline so the interval that is
    computed and the confidence level that is printed beside it cannot drift
    apart. It is the conservative choice deliberately: the alternatives assume
    something about how the populations depend on one another, and closure
    constrains that dependence in a way this design does not pin down.
    """
    return alpha / n_tested if n_tested > 0 else alpha


# Below this, 1 - tail rounds to 1.0 in double precision and the inverse CDF
# has nothing left to invert.
_SMALLEST_USABLE_TAIL = 1e-15


def _interval(
    differences: npt.NDArray[np.float64], n_left: int, n_right: int, alpha: float
) -> tuple[float, float] | None:
    """Invert the rank test at `alpha` by cutting k in from each end.

    `differences` must already be sorted, and must be every left-minus-right
    pair, or the index arithmetic below means nothing.

    Returns None when the groups are too small to support an interval at this
    level. With m = n = 4 there are 16 pairwise differences and their full range
    covers about 97%, so a 99% interval does not exist. Clamping to the full
    range instead would return the marginal 95% interval under a 99% label, and
    a caller printing both would show identical numbers in adjacent columns
    headed 95% and 99%.
    """
    total = int(differences.size)
    # 1 - alpha/2 rounds to exactly 1.0 below about 2e-16, and NormalDist then
    # raises from inside statistics with a message that never mentions alpha.
    # `compare` validates the level it was given, but dividing by n_tested for
    # the simultaneous interval can push the derived level under that floor.
    tail = max(alpha / 2.0, _SMALLEST_USABLE_TAIL)
    z = float(NormalDist().inv_cdf(1 - tail))
    spread = math.sqrt(n_left * n_right * (n_left + n_right + 1) / 12.0)
    # Coverage of [D_(k+1), D_(mn-k)] is 1 - 2*P(U <= k), so the cut is the
    # largest k with P(U <= k) <= alpha/2. The normal approximation gives the
    # quantile itself; stepping one below it is what keeps the interval
    # conservative rather than overclaiming.
    k = int(round(n_left * n_right / 2.0 - z * spread)) - 1
    # A narrow alpha against few pairs drives k below zero, which means the
    # requested level is unreachable rather than that it needs clamping. The
    # upper bound is unreachable in the other direction, since k <= mn/2 - 1
    # for every alpha in (0, 1), so it is asserted rather than applied.
    if k < 0:
        return None
    assert k <= (total - 1) // 2, "interval indices would cross"
    return (float(differences[k]), float(differences[total - 1 - k]))


def _shift_and_intervals(
    left: list[float], right: list[float], alphas: Sequence[float]
) -> tuple[float, list[tuple[float, float] | None]]:
    """Hodges-Lehmann shift and one interval per level in `alphas`.

    The shift is the median of all pairwise differences, which is the location
    estimate Mann-Whitney actually tests, so it cannot disagree with the
    p-value the way a difference of means could. Each interval comes from
    inverting the same test.

    Every level is served from one sorted array. Computing them separately
    built the m*n differences once per level, which on the unfiltered cohort
    meant 20 million values materialised four times over and turned a 0.1
    second call into more than a minute.
    """
    differences = np.sort(
        (
            np.asarray(left, dtype=float)[:, None]
            - np.asarray(right, dtype=float)[None, :]
        ).ravel()
    )
    n_left, n_right = len(left), len(right)
    return (
        float(np.median(differences)),
        [_interval(differences, n_left, n_right, alpha) for alpha in alphas],
    )


_BASE_SQL = """
SELECT
    {split_column} AS grp,
    samples.sample_id,
    samples.subject_id,
    sample_frequencies.population,
    sample_frequencies.percentage
FROM sample_frequencies
JOIN samples USING (sample_id)
JOIN subjects USING (subject_id)
"""


def compare(
    conn: sqlite3.Connection,
    cohort: Cohort = ALL_SAMPLES,
    split_on: str = "response",
    alpha: float = 0.05,
) -> ComparisonResult:
    """Compare population frequencies between the two groups of `split_on`.

    Rows where the split column is NULL are excluded: an untreated control has
    no response to compare, which is not the same as belonging to a third group.

    Raises `UnknownSplitColumn` if `split_on` is not a splittable column, and
    `NotTwoGroups` if the cohort does not yield exactly two groups. Both
    subclass `ComparisonError`, which subclasses `ValueError`.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must lie strictly between 0 and 1, got {alpha!r}")

    if split_on not in _SPLIT_COLUMNS:
        raise UnknownSplitColumn(
            f"cannot split on {split_on!r}; expected one of {sorted(_SPLIT_COLUMNS)}"
        )

    split_column = _SPLIT_COLUMNS[split_on]
    fragments, params = conditions(cohort)
    fragments.append(f"{split_column} IS NOT NULL")
    sql = _BASE_SQL.format(split_column=split_column) + render_where(fragments)

    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return ComparisonResult(
            cohort=cohort,
            split_on=split_on,
            groups=(),
            n_samples={},
            n_subjects={},
            repeated_measures=False,
            n_tested=0,
            alpha=alpha,
            populations=[],
        )

    groups = tuple(sorted({row[0] for row in rows}))
    if len(groups) != 2:
        raise NotTwoGroups(
            f"comparison needs exactly two groups of {split_on!r}, "
            f"but this cohort has {len(groups)}: {list(groups)}"
        )

    samples_by_group: dict[str, set[str]] = {g: set() for g in groups}
    subjects_by_group: dict[str, set[str]] = {g: set() for g in groups}
    values: dict[str, dict[str, list[float]]] = {}

    for group, sample_id, subject_id, population, percentage in rows:
        samples_by_group[group].add(sample_id)
        subjects_by_group[group].add(subject_id)
        values.setdefault(population, {g: [] for g in groups})[group].append(percentage)

    n_samples = {g: len(s) for g, s in samples_by_group.items()}
    n_subjects = {g: len(s) for g, s in subjects_by_group.items()}

    first, second = groups
    # A population present in only one group has nothing to compare, and its
    # median would be taken over an empty list. Drop it rather than raise:
    # StatisticsError subclasses ValueError, so it would otherwise be
    # indistinguishable from a caller error at the API boundary.
    populations = sorted(
        population
        for population, by_group in values.items()
        if all(by_group[group] for group in groups)
    )
    p_values: dict[str, float] = {}
    effect_sizes: dict[str, float] = {}
    shifts: dict[str, float] = {}
    # Either can be None when the groups are too small to support an interval at
    # that level, which the simultaneous one reaches first because its level is
    # narrower by a factor of n_tested.
    intervals: dict[str, tuple[float, float] | None] = {}
    joint_intervals: dict[str, tuple[float, float] | None] = {}

    # First pass: the p-values, which are what decide the size of the family.
    # The intervals cannot be computed until that size is known, because the
    # simultaneous one is taken at alpha divided by it.
    for population in populations:
        left = values[population][first]
        right = values[population][second]
        if min(len(left), len(right)) < MIN_GROUP_SIZE:
            continue
        test = mannwhitneyu(left, right, alternative="two-sided")
        p_value = float(test.pvalue)
        if not math.isfinite(p_value):
            # Every observation in both groups is identical, so the tie
            # correction divides by zero. Leave this population untested rather
            # than letting a nan reach the correction and take the batch down.
            continue
        p_values[population] = p_value
        # U is independent of `alternative`, so it comes from the same call.
        effect_sizes[population] = float(test.statistic) / (len(left) * len(right))

    # Second pass: the shift and both intervals, from one difference array per
    # population. Splitting the loop costs a second Mann-Whitney-free walk of
    # the tested populations; recomputing the differences would cost far more.
    joint_alpha = simultaneous_alpha(alpha, len(p_values))
    for population in p_values:
        (
            shifts[population],
            (
                intervals[population],
                joint_intervals[population],
            ),
        ) = _shift_and_intervals(
            values[population][first], values[population][second], (alpha, joint_alpha)
        )

    # Correct only across populations that were actually tested.
    q_values: dict[str, float] = {}
    if p_values:
        tested = sorted(p_values)
        adjusted = false_discovery_control([p_values[p] for p in tested], method="bh")
        q_values = {p: float(q) for p, q in zip(tested, adjusted, strict=True)}

    comparisons = [
        PopulationComparison(
            population=population,
            n={g: len(values[population][g]) for g in groups},
            median={g: median(values[population][g]) for g in groups},
            values={g: list(values[population][g]) for g in groups},
            p_value=p_values.get(population),
            q_value=q_values.get(population),
            shift=shifts.get(population),
            shift_ci=intervals.get(population),
            simultaneous_ci=joint_intervals.get(population),
            effect_size=effect_sizes.get(population),
        )
        for population in populations
    ]

    return ComparisonResult(
        cohort=cohort,
        split_on=split_on,
        groups=groups,
        n_samples=n_samples,
        n_subjects=n_subjects,
        repeated_measures=any(n_samples[g] > n_subjects[g] for g in groups),
        n_tested=len(p_values),
        alpha=alpha,
        populations=comparisons,
    )


def yekutieli_q_values(result: ComparisonResult) -> dict[str, float]:
    """The same p-values re-corrected under Benjamini-Yekutieli.

    Benjamini-Hochberg controls the false discovery rate under independence or
    positive regression dependence. Frequencies that sum to 100 cannot all be
    positively related, since closure forces each part's covariances with the
    rest to sum to minus its own variance, so neither condition is established
    for this data and the guarantee is asserted rather than earned.

    Benjamini-Yekutieli holds under arbitrary dependence, at the cost of a
    factor of sum(1/i) in power. That makes it a sensitivity check on the
    headline correction rather than a replacement for it: a conclusion that
    survives both does not turn on the assumption.

    Returns an empty mapping when nothing was tested, which is the same thing
    `q_value` being None says on each population.
    """
    p_values = {
        comparison.population: comparison.p_value
        for comparison in result.populations
        if comparison.p_value is not None
    }
    if not p_values:
        return {}
    tested = sorted(p_values)
    adjusted = false_discovery_control([p_values[p] for p in tested], method="by")
    return {p: float(q) for p, q in zip(tested, adjusted, strict=True)}
