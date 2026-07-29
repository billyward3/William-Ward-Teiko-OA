"""Mean absolute cell counts over a cohort.

Distinct from `summary.py`, which reports relative frequencies. A frequency
answers "what proportion of this sample was B cells"; this answers "how many B
cells were there". The two diverge whenever total counts differ between samples,
which is the whole reason compositional data needs care.

The submission form asks for one of these, over a cohort deliberately looser
than Part 4's: melanoma males across all sample types and all treatments. Since
`Cohort` treats None as unconstrained, that is expressible without a special
case, and the difference from Part 4 is visible at the call site.
"""

from __future__ import annotations

import sqlite3

from cellcount.cohort import ALL_SAMPLES, Cohort, conditions, render_where
from cellcount.loader import POPULATIONS

_SQL = """
SELECT AVG(cell_counts.count)
FROM cell_counts
JOIN populations USING (population_id)
JOIN samples USING (sample_id)
JOIN subjects USING (subject_id)
"""


def mean_count(
    conn: sqlite3.Connection,
    cohort: Cohort = ALL_SAMPLES,
    population: str = "b_cell",
) -> float | None:
    """Mean absolute count of `population` across the cohort's samples.

    Returns None when the cohort matches nothing, rather than raising or
    reporting 0.0, which would be indistinguishable from a real mean of zero.

    Raises ValueError for an unknown population name, which would otherwise
    silently match no rows and look like an empty cohort.
    """
    if population not in POPULATIONS:
        raise ValueError(
            f"unknown population {population!r}; expected one of {sorted(POPULATIONS)}"
        )

    fragments, params = conditions(cohort)
    fragments.append("populations.name = ?")
    params.append(population)

    result = conn.execute(_SQL + render_where(fragments), params).fetchone()[0]
    return None if result is None else float(result)
