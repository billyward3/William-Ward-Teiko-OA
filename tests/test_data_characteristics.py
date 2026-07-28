"""Characterization tests for cell-count.csv.

These assert properties of the *input data* that the database schema depends on.
They are deliberately not tests of our own code. If one fails, the data has
changed shape and the schema needs revisiting; it does not mean there is a bug
to fix.

The file is read with the stdlib csv module rather than pandas so the
assertions apply to the literal contents, with no type coercion or NaN
substitution in between.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import pytest

EXPECTED_COLUMNS = [
    "project",
    "subject",
    "condition",
    "age",
    "sex",
    "treatment",
    "response",
    "sample",
    "sample_type",
    "time_from_treatment_start",
    "b_cell",
    "cd8_t_cell",
    "cd4_t_cell",
    "nk_cell",
    "monocyte",
]

POPULATION_COLUMNS = ["b_cell", "cd8_t_cell", "cd4_t_cell", "nk_cell", "monocyte"]

# Attributes the schema intends to store once per subject rather than per
# sample. Each must be constant across all of that subject's samples, or it
# belongs on the sample instead.
SUBJECT_LEVEL_COLUMNS = [
    "project",
    "condition",
    "age",
    "sex",
    "treatment",
    "response",
]


@pytest.fixture(scope="module")
def rows(cell_count_csv: Path) -> list[dict[str, str]]:
    with cell_count_csv.open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_csv_exists(cell_count_csv: Path) -> None:
    assert cell_count_csv.is_file(), f"missing input data at {cell_count_csv}"


def test_header_matches_expected_columns(rows: list[dict[str, str]]) -> None:
    assert list(rows[0].keys()) == EXPECTED_COLUMNS


def test_sample_ids_are_unique(rows: list[dict[str, str]]) -> None:
    ids = [row["sample"] for row in rows]
    assert len(ids) == len(set(ids))


def test_population_counts_are_non_negative_integers(
    rows: list[dict[str, str]],
) -> None:
    offenders = [
        (row["sample"], column, row[column])
        for row in rows
        for column in POPULATION_COLUMNS
        if not row[column].isdigit()
    ]
    assert not offenders, f"non-integer counts: {offenders[:5]}"


@pytest.mark.parametrize("column", SUBJECT_LEVEL_COLUMNS)
def test_attribute_is_constant_within_subject(
    rows: list[dict[str, str]], column: str
) -> None:
    values: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        values[row["subject"]].add(row[column])

    offenders = {
        subject: sorted(seen) for subject, seen in values.items() if len(seen) > 1
    }
    assert not offenders, (
        f"{column} varies within {len(offenders)} subject(s), so it is "
        f"sample-level, not subject-level. Examples: "
        f"{dict(list(offenders.items())[:3])}"
    )


def test_subject_sample_type_and_timepoint_identify_one_sample(
    rows: list[dict[str, str]],
) -> None:
    """A subject should not have two samples of the same type at the same time.

    If this holds it is a natural uniqueness constraint for the samples table,
    independent of the surrogate sample id.
    """
    seen: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for row in rows:
        key = (row["subject"], row["sample_type"], row["time_from_treatment_start"])
        seen[key].append(row["sample"])

    collisions = {key: ids for key, ids in seen.items() if len(ids) > 1}
    assert not collisions, (
        f"{len(collisions)} (subject, sample_type, timepoint) tuple(s) map to "
        f"more than one sample. Examples: {dict(list(collisions.items())[:3])}"
    )
