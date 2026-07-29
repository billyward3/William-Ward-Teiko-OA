"""Part 3: comparing population frequencies between two groups.

Three decisions are encoded here rather than left to the caller.

**Mann-Whitney U** rather than a t-test. Relative frequencies are bounded on
[0, 100] and need not be normally distributed, and a rank test assumes neither.
Note it tests stochastic dominance, so it is a test of medians only when the two
distributions share a shape.

**Benjamini-Hochberg across all five populations.** Five tests at alpha = 0.05
carry roughly a 23% chance of at least one false positive. Controlling the false
discovery rate is the right choice for screening, and it is why every population
is computed in one call: a q-value depends on the whole set of p-values.

**Independence is reported, not assumed.** Each subject in the real data has
three samples, so a cohort spanning timepoints pools correlated observations and
inflates the effective sample size. `n_samples`, `n_subjects`, and
`repeated_measures` make that visible to whoever reads the result.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from statistics import median

from scipy.stats import false_discovery_control, mannwhitneyu

from cellcount.cohort import ALL_SAMPLES, FILTER_COLUMNS, Cohort, where_clause

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


@dataclass(frozen=True)
class PopulationComparison:
    population: str
    n: dict[str, int]
    median: dict[str, float]
    values: dict[str, list[float]]
    p_value: float | None
    q_value: float | None
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
    populations: list[PopulationComparison]


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
) -> ComparisonResult:
    """Compare population frequencies between the two groups of `split_on`.

    Rows where the split column is NULL are excluded: an untreated control has
    no response to compare, which is not the same as belonging to a third group.

    Raises ValueError if `split_on` is not a known column, or if the cohort does
    not yield exactly two groups.
    """
    if split_on not in _SPLIT_COLUMNS:
        raise ValueError(
            f"cannot split on {split_on!r}; expected one of {sorted(_SPLIT_COLUMNS)}"
        )

    split_column = _SPLIT_COLUMNS[split_on]
    clause, params = where_clause(cohort)
    null_filter = f"{split_column} IS NOT NULL"
    clause = f"{clause} AND {null_filter}" if clause else f"WHERE {null_filter}"
    sql = _BASE_SQL.format(split_column=split_column) + clause

    rows = conn.execute(sql, params).fetchall()
    if not rows:
        return ComparisonResult(
            cohort=cohort,
            split_on=split_on,
            groups=(),
            n_samples={},
            n_subjects={},
            repeated_measures=False,
            populations=[],
        )

    groups = tuple(sorted({row[0] for row in rows}))
    if len(groups) != 2:
        raise ValueError(
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
    populations = sorted(values)
    p_values: dict[str, float] = {}
    effect_sizes: dict[str, float] = {}

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
        populations=comparisons,
    )
