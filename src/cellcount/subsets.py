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


def _counts_by(
    conn: sqlite3.Connection,
    cohort: Cohort,
    column: str,
    *,
    distinct_subjects: bool,
    exclude_null: bool = False,
) -> dict[str, int]:
    fragments, params = conditions(cohort)
    if exclude_null:
        fragments.append(f"{column} IS NOT NULL")
    measure = "COUNT(DISTINCT samples.subject_id)" if distinct_subjects else "COUNT(*)"
    sql = (
        f"SELECT {column}, {measure} {_FROM} {render_where(fragments)} "
        f"GROUP BY {column} ORDER BY {column}"
    )
    return {row[0]: row[1] for row in conn.execute(sql, params)}


def subset_counts(
    conn: sqlite3.Connection, cohort: Cohort = ALL_SAMPLES
) -> SubsetCounts:
    """Break a cohort down by project, response, and sex.

    Note the counting units differ, matching how the spec words each question.
    """
    present = _counts_by(conn, cohort, "subjects.project_id", distinct_subjects=False)
    # Every known project appears, so an absent one reads as zero rather than
    # as a project that does not exist.
    all_projects = [
        row[0]
        for row in conn.execute("SELECT project_id FROM projects ORDER BY project_id")
    ]
    samples_per_project = {project: present.get(project, 0) for project in all_projects}

    return SubsetCounts(
        samples_per_project=samples_per_project,
        subjects_per_response=_counts_by(
            conn,
            cohort,
            "subjects.response",
            distinct_subjects=True,
            exclude_null=True,
        ),
        subjects_per_sex=_counts_by(
            conn, cohort, "subjects.sex", distinct_subjects=True
        ),
    )
