"""Part 2: relative frequency of each population within each sample.

The arithmetic lives in the `sample_frequencies` view (see `db.py`), not here.
This module joins that view to the dimensions a cohort filters on and returns
typed rows.

The spec fixes the output columns, so `SummaryRow` field names are part of the
contract rather than an internal choice.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from cellcount.cohort import ALL_SAMPLES, Cohort, where_clause


@dataclass(frozen=True)
class SummaryRow:
    sample: str
    total_count: int
    population: str
    count: int
    percentage: float


_BASE_SQL = """
SELECT
    sample_frequencies.sample_id AS sample,
    sample_frequencies.total_count,
    sample_frequencies.population,
    sample_frequencies.count,
    sample_frequencies.percentage
FROM sample_frequencies
JOIN samples USING (sample_id)
JOIN subjects USING (subject_id)
"""

_ORDER_BY = "ORDER BY sample_frequencies.sample_id, sample_frequencies.population"


def summary_rows(
    conn: sqlite3.Connection, cohort: Cohort = ALL_SAMPLES
) -> list[SummaryRow]:
    """Return one row per sample and population.

    An unfiltered call produces the table the spec asks for. The cohort
    parameter exists so the dashboard can narrow the same query rather than
    duplicating it.
    """
    clause, params = where_clause(cohort)
    sql = f"{_BASE_SQL} {clause} {_ORDER_BY}"
    return [
        SummaryRow(
            sample=row[0],
            total_count=row[1],
            population=row[2],
            count=row[3],
            percentage=row[4],
        )
        for row in conn.execute(sql, params)
    ]
