"""Part 4: breakdowns of a filtered subset.

The spec asks three questions in two different counting units. Samples per
project counts rows in `samples`; responders and sexes count distinct
*subjects*. Getting that wrong is invisible in the delivered data, because at
baseline every subject contributes exactly one sample and the two coincide, so
the distinction is enforced in SQL rather than left to a reader to notice.

Projects with no matching samples are reported as zero rather than omitted. A
`GROUP BY` naturally drops them, which reads as though the project does not
exist; the real data has exactly this case.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from cellcount.cohort import ALL_SAMPLES, Cohort, conditions, render_where


@dataclass(frozen=True)
class SubsetCounts:
    samples_per_project: dict[str, int]
    subjects_per_response: dict[str, int]
    subjects_per_sex: dict[str, int]


_FROM = """
FROM samples
JOIN subjects USING (subject_id)
"""

# `column` is interpolated into SQL rather than bound, because a column name
# cannot be a bound parameter. Every caller below passes a literal, but the
# allowlist means that stays true even if one day a caller passes a variable.
_GROUPABLE_COLUMNS = frozenset(
    {"subjects.project_id", "subjects.response", "subjects.sex"}
)


def _counts_by(
    conn: sqlite3.Connection,
    cohort: Cohort,
    column: str,
    *,
    distinct_subjects: bool,
    exclude_null: bool = False,
) -> dict[str, int]:
    if column not in _GROUPABLE_COLUMNS:
        raise ValueError(f"cannot group by {column!r}")

    fragments, params = conditions(cohort)
    if exclude_null:
        fragments.append(f"{column} IS NOT NULL")
    measure = "COUNT(DISTINCT samples.subject_id)" if distinct_subjects else "COUNT(*)"
    sql = (
        f"SELECT {column}, {measure} {_FROM} {render_where(fragments)} "
        f"GROUP BY {column} ORDER BY {column}"
    )
    return {row[0]: row[1] for row in conn.execute(sql, params)}


def _known_values(conn: sqlite3.Connection, column: str) -> list[str]:
    """Every value a column takes across the whole dataset, not just this cohort.

    Used to zero-fill, so a category the cohort excludes is reported as absent
    rather than simply missing from the result.
    """
    if column not in _GROUPABLE_COLUMNS:
        raise ValueError(f"cannot enumerate {column!r}")
    _, _, name = column.partition(".")
    return [
        row[0]
        for row in conn.execute(
            f"SELECT DISTINCT {name} FROM subjects "
            f"WHERE {name} IS NOT NULL ORDER BY {name}"
        )
    ]


def subset_counts(
    conn: sqlite3.Connection, cohort: Cohort = ALL_SAMPLES
) -> SubsetCounts:
    """Break a cohort down by project, response, and sex.

    Note the counting units differ, matching how the spec words each question.

    Every category known to the dataset appears, including those the cohort
    matched zero of. Omitting them reads as though the category does not exist,
    and a client rendering "responders versus non-responders" would otherwise
    get a missing key rather than a zero.
    """

    def filled(
        column: str, *, distinct_subjects: bool, domain: list[str]
    ) -> dict[str, int]:
        present = _counts_by(
            conn,
            cohort,
            column,
            distinct_subjects=distinct_subjects,
            exclude_null=True,
        )
        return {value: present.get(value, 0) for value in domain}

    # Projects come from their own table, which is authoritative: a project
    # with no subjects at all still exists and should still be listed.
    all_projects = [
        row[0]
        for row in conn.execute("SELECT project_id FROM projects ORDER BY project_id")
    ]

    return SubsetCounts(
        samples_per_project=filled(
            "subjects.project_id", distinct_subjects=False, domain=all_projects
        ),
        subjects_per_response=filled(
            "subjects.response",
            distinct_subjects=True,
            domain=_known_values(conn, "subjects.response"),
        ),
        subjects_per_sex=filled(
            "subjects.sex",
            distinct_subjects=True,
            domain=_known_values(conn, "subjects.sex"),
        ),
    )
