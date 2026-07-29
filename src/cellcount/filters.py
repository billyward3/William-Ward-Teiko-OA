"""What values each cohort field can take.

A dashboard has to offer these rather than accept free text. `Cohort` filters
are exact-match and case-sensitive, so `condition = "Melanoma"` is not a near
miss, it is an empty result with nothing to say why. Reading the choices out of
the database removes the class of mistake entirely, and keeps working if the
data grows a fourth condition.

The values come from the same columns `cohort.py` filters on, so a new filter
appears in the dropdowns without a second edit here.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from cellcount.cohort import FILTER_COLUMNS, TIMEPOINT_COLUMN

# Column names cannot be bound parameters, so they are interpolated. Every one
# comes from the mapping above rather than from a request, and the allowlist
# keeps that true if a caller ever passes a variable.
_SELECTABLE_COLUMNS = frozenset(FILTER_COLUMNS.values()) | {TIMEPOINT_COLUMN}


@dataclass(frozen=True)
class FilterOptions:
    """Every choice a client can offer, taken from the data rather than declared."""

    fields: dict[str, list[str]]
    """Cohort field name -> the values it can take. Keyed to match the query
    parameters, so a client can build one control per entry."""

    timepoints: list[int]
    """Distinct `time_from_treatment_start` values, in numeric order."""

    populations: list[str]
    """The populations `mean_count` will accept, from the dimension table."""


def _distinct[T](
    conn: sqlite3.Connection, qualified: str, convert: Callable[[Any], T]
) -> list[T]:
    """Distinct non-NULL values of an allowlisted column, in the column's order.

    NULL is excluded because it is not selectable: `response` is NULL for
    untreated controls, meaning the question does not apply to them, and a
    dropdown entry for it would build a cohort that matches nothing.

    `convert` narrows what sqlite3 hands back, which is untyped. It also fixes
    the ordering claim: timepoints are ordered as the INTEGER column they are,
    so 7 precedes 14 rather than following it.
    """
    if qualified not in _SELECTABLE_COLUMNS:
        raise ValueError(f"cannot enumerate {qualified!r}")
    table, _, column = qualified.partition(".")
    sql = (
        f"SELECT DISTINCT {column} FROM {table} "
        f"WHERE {column} IS NOT NULL ORDER BY {column}"
    )
    return [convert(row[0]) for row in conn.execute(sql)]


def filter_options(conn: sqlite3.Connection) -> FilterOptions:
    """Enumerate the values every cohort field takes in this database.

    An empty database yields empty lists rather than raising: that is what the
    schema says before a load has run, and a client showing empty dropdowns is
    a better failure than one showing an error it cannot act on.
    """
    return FilterOptions(
        fields={
            field: _distinct(conn, column, str)
            for field, column in FILTER_COLUMNS.items()
        },
        timepoints=_distinct(conn, TIMEPOINT_COLUMN, int),
        populations=[
            str(row[0])
            for row in conn.execute("SELECT name FROM populations ORDER BY name")
        ],
    )
