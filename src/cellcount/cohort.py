"""Cohort selection: which samples an analysis looks at.

One vocabulary with three representations. As a dataclass it is what analysis
functions take; as SQL it is a WHERE clause; over HTTP it is query parameters.
Keeping the translation in one place means a new filter is added once.

`None` means unconstrained rather than "match nothing", so the spec's Part 3
cohort and the form question's much looser one are both expressible without
special cases.
"""

from __future__ import annotations

from dataclasses import dataclass

# Cohort field -> the qualified column it filters on. Order fixes the order of
# conditions in the emitted SQL, so the same cohort always produces the same
# statement text and SQLite can reuse the prepared statement.
FILTER_COLUMNS: dict[str, str] = {
    "condition": "subjects.condition",
    "treatment": "subjects.treatment",
    "response": "subjects.response",
    "sex": "subjects.sex",
    "sample_type": "samples.sample_type",
}

_TIMEPOINT_COLUMN = "samples.time_from_treatment_start"


@dataclass(frozen=True)
class Cohort:
    """A filter over samples. Every field defaults to unconstrained."""

    condition: str | None = None
    treatment: str | None = None
    response: str | None = None
    sex: str | None = None
    sample_type: str | None = None
    timepoints: tuple[int, ...] | None = None


ALL_SAMPLES = Cohort()
"""The unconstrained cohort: every sample in the database.

Frozen, so it is safe to share as a default argument.
"""


def where_clause(cohort: Cohort) -> tuple[str, list[object]]:
    """Build a parameterized WHERE clause for a cohort.

    Returns the SQL fragment including the WHERE keyword, or an empty string if
    the cohort constrains nothing, so it can be interpolated straight after a
    FROM clause either way.

    Every value is returned as a bound parameter. Nothing the caller supplies is
    ever formatted into the SQL text.
    """
    conditions: list[str] = []
    params: list[object] = []

    for field, column in FILTER_COLUMNS.items():
        value = getattr(cohort, field)
        if value is not None:
            conditions.append(f"{column} = ?")
            params.append(value)

    if cohort.timepoints:
        placeholders = ", ".join("?" for _ in cohort.timepoints)
        conditions.append(f"{_TIMEPOINT_COLUMN} IN ({placeholders})")
        params.extend(cohort.timepoints)

    if not conditions:
        return "", []
    return "WHERE " + " AND ".join(conditions), params
