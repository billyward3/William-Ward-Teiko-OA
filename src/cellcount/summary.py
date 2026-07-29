"""Part 2: relative frequency of each population within each sample.

The arithmetic lives in the `sample_frequencies` view (see `db.py`), not here.
This module joins that view to the dimensions a cohort filters on and returns
typed rows.

The spec fixes the output columns, so `SummaryRow` field names are part of the
contract rather than an internal choice.

Results are paginated. Unfiltered, this table is one row per sample and
population, which is 52,500 rows for the delivered data and around 6.6 MB of
JSON: too much to hand a browser in one response. The page carries the total
count as well, because otherwise a client cannot tell how many pages exist.
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


@dataclass(frozen=True)
class SummaryPage:
    rows: list[SummaryRow]
    total: int
    """Rows matching the cohort before limit and offset are applied."""


_SELECT = """
SELECT
    sample_frequencies.sample_id AS sample,
    sample_frequencies.total_count,
    sample_frequencies.population,
    sample_frequencies.count,
    sample_frequencies.percentage
"""

_FROM = """
FROM sample_frequencies
JOIN samples USING (sample_id)
JOIN subjects USING (subject_id)
"""

_ORDER_BY = "ORDER BY sample_frequencies.sample_id, sample_frequencies.population"


def summary_page(
    conn: sqlite3.Connection,
    cohort: Cohort = ALL_SAMPLES,
    *,
    limit: int | None = None,
    offset: int = 0,
) -> SummaryPage:
    """One row per sample and population, ordered and optionally paginated.

    Calling with no arguments produces exactly the table the spec asks for. The
    cohort narrows it; `limit` and `offset` page through it. The ordering is a
    total one, so paging is stable.

    Raises ValueError for a negative limit or offset. SQLite reads a negative
    LIMIT as unbounded, so passing one through would quietly return the whole
    table, defeating the point of paginating at all.
    """
    if limit is not None and limit < 0:
        raise ValueError(f"limit cannot be negative, got {limit}")
    if offset < 0:
        raise ValueError(f"offset cannot be negative, got {offset}")

    clause, params = where_clause(cohort)

    total: int = conn.execute(f"SELECT COUNT(*) {_FROM} {clause}", params).fetchone()[0]

    sql = f"{_SELECT} {_FROM} {clause} {_ORDER_BY}"
    page_params: list[object] = list(params)
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        page_params += [limit, offset]
    elif offset:
        # SQLite requires a LIMIT before OFFSET; -1 means unbounded.
        sql += " LIMIT -1 OFFSET ?"
        page_params.append(offset)

    rows = [
        SummaryRow(
            sample=row[0],
            total_count=row[1],
            population=row[2],
            count=row[3],
            percentage=row[4],
        )
        for row in conn.execute(sql, page_params)
    ]
    return SummaryPage(rows=rows, total=total)
