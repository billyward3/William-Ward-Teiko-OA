"""Tests for the Part 4 subset breakdowns.

The spec words the three questions with two different counting units: samples
per project, but *subjects* by response and by sex. That distinction is the
point of these tests, because in the real data it happens to be invisible: at
baseline every subject contributes exactly one sample, so the two counts
coincide and a query using the wrong grain would still look right.

The fixtures here deliberately give subjects several samples so the two diverge.
"""

from __future__ import annotations

import sqlite3

import pytest

from cellcount.cohort import Cohort
from cellcount.db import create_schema
from cellcount.loader import POPULATIONS
from cellcount.subsets import subset_counts


def _add_subject(
    conn: sqlite3.Connection,
    subject: str,
    *,
    project: str = "prj1",
    condition: str = "melanoma",
    sex: str = "M",
    treatment: str = "miraclib",
    response: str | None = "yes",
    timepoints: tuple[int, ...] = (0,),
    sample_type: str = "PBMC",
) -> None:
    conn.execute("INSERT OR IGNORE INTO projects (project_id) VALUES (?)", (project,))
    conn.execute(
        "INSERT INTO subjects "
        "(subject_id, project_id, condition, age, sex, treatment, response) "
        "VALUES (?, ?, ?, 50, ?, ?, ?)",
        (subject, project, condition, sex, treatment, response),
    )
    for timepoint in timepoints:
        sample = f"{subject}-t{timepoint}"
        conn.execute(
            "INSERT INTO samples (sample_id, subject_id, sample_type, "
            "time_from_treatment_start) VALUES (?, ?, ?, ?)",
            (sample, subject, sample_type, timepoint),
        )
        conn.executemany(
            "INSERT INTO cell_counts (sample_id, population_id, count) "
            "VALUES (?, ?, ?)",
            [(sample, i + 1, 40) for i in range(len(POPULATIONS))],
        )


@pytest.fixture
def db(conn: sqlite3.Connection) -> sqlite3.Connection:
    create_schema(conn)
    conn.executemany(
        "INSERT INTO populations (population_id, name) VALUES (?, ?)",
        list(enumerate(POPULATIONS, start=1)),
    )
    for project in ("prj1", "prj2", "prj3"):
        conn.execute("INSERT INTO projects (project_id) VALUES (?)", (project,))
    return conn


def test_samples_per_project_counts_samples_not_subjects(
    db: sqlite3.Connection,
) -> None:
    """One subject with three samples must count as three."""
    _add_subject(db, "sbj1", project="prj1", timepoints=(0, 7, 14))
    _add_subject(db, "sbj2", project="prj3", timepoints=(0,))
    db.commit()

    counts = subset_counts(db, Cohort())
    assert counts.samples_per_project["prj1"] == 3
    assert counts.samples_per_project["prj3"] == 1


def test_subjects_by_response_counts_subjects_not_samples(
    db: sqlite3.Connection,
) -> None:
    """The same subject with three samples must count once."""
    _add_subject(db, "sbj1", response="yes", timepoints=(0, 7, 14))
    _add_subject(db, "sbj2", response="no", timepoints=(0, 7))
    db.commit()

    counts = subset_counts(db, Cohort())
    assert counts.subjects_per_response == {"no": 1, "yes": 1}


def test_subjects_by_sex_counts_subjects_not_samples(db: sqlite3.Connection) -> None:
    _add_subject(db, "sbj1", sex="M", timepoints=(0, 7, 14))
    _add_subject(db, "sbj2", sex="F", timepoints=(0,))
    db.commit()

    counts = subset_counts(db, Cohort())
    assert counts.subjects_per_sex == {"F": 1, "M": 1}


def test_the_two_grains_diverge(db: sqlite3.Connection) -> None:
    """The distinction the spec draws, made visible in one assertion."""
    _add_subject(db, "sbj1", timepoints=(0, 7, 14))
    _add_subject(db, "sbj2", timepoints=(0, 7, 14))
    db.commit()

    counts = subset_counts(db, Cohort())
    assert sum(counts.samples_per_project.values()) == 6
    assert sum(counts.subjects_per_response.values()) == 2


def test_a_project_with_no_matching_samples_reports_zero(
    db: sqlite3.Connection,
) -> None:
    """Silently omitting it would read as though the project did not exist.

    Real data does this: prj2 has no melanoma / miraclib / PBMC baseline samples.
    """
    _add_subject(db, "sbj1", project="prj1")
    db.commit()

    counts = subset_counts(db, Cohort())
    assert counts.samples_per_project == {"prj1": 1, "prj2": 0, "prj3": 0}


def test_the_cohort_filter_applies(db: sqlite3.Connection) -> None:
    _add_subject(db, "sbj1", condition="melanoma", timepoints=(0, 7))
    _add_subject(db, "sbj2", condition="carcinoma", timepoints=(0,))
    db.commit()

    counts = subset_counts(db, Cohort(condition="melanoma", timepoints=(0,)))
    assert counts.samples_per_project["prj1"] == 1
    assert sum(counts.subjects_per_response.values()) == 1


def test_subjects_with_no_response_are_excluded(db: sqlite3.Connection) -> None:
    """A healthy control is neither a responder nor a non-responder."""
    _add_subject(db, "sbj1", response="yes")
    _add_subject(db, "sbj2", condition="healthy", treatment="none", response=None)
    db.commit()

    counts = subset_counts(db, Cohort())
    assert counts.subjects_per_response == {"yes": 1}
    # But they still have a sex, so they are counted there.
    assert sum(counts.subjects_per_sex.values()) == 2


def test_an_empty_cohort_reports_zeros_rather_than_nothing(
    db: sqlite3.Connection,
) -> None:
    _add_subject(db, "sbj1", sex="M", response="yes")
    _add_subject(db, "sbj2", sex="F", response="no")
    db.commit()

    counts = subset_counts(db, Cohort(condition="nonexistent"))
    assert counts.samples_per_project == {"prj1": 0, "prj2": 0, "prj3": 0}
    assert counts.subjects_per_response == {"no": 0, "yes": 0}
    assert counts.subjects_per_sex == {"F": 0, "M": 0}


def test_an_excluded_response_arm_reports_zero(db: sqlite3.Connection) -> None:
    """A client rendering "responders vs non-responders" needs both keys."""
    _add_subject(db, "sbj1", response="yes")
    _add_subject(db, "sbj2", response="no")
    db.commit()

    counts = subset_counts(db, Cohort(response="yes"))
    assert counts.subjects_per_response == {"no": 0, "yes": 1}


def test_an_excluded_sex_reports_zero(db: sqlite3.Connection) -> None:
    _add_subject(db, "sbj1", sex="M")
    _add_subject(db, "sbj2", sex="F")
    db.commit()

    counts = subset_counts(db, Cohort(sex="M"))
    assert counts.subjects_per_sex == {"F": 0, "M": 1}


def test_grouping_by_an_unlisted_column_is_rejected(db: sqlite3.Connection) -> None:
    """The one interpolated identifier is allowlisted, as in comparison.py."""
    from cellcount.subsets import _counts_by, _known_values

    with pytest.raises(ValueError, match="group by"):
        _counts_by(db, Cohort(), "subjects.age", distinct_subjects=False)
    with pytest.raises(ValueError, match="enumerate"):
        _known_values(db, "subjects; DROP TABLE samples")


def test_keys_are_ordered_deterministically(db: sqlite3.Connection) -> None:
    _add_subject(db, "sbj1", project="prj3", sex="M", response="yes")
    _add_subject(db, "sbj2", project="prj1", sex="F", response="no")
    db.commit()

    counts = subset_counts(db, Cohort())
    assert list(counts.samples_per_project) == sorted(counts.samples_per_project)
    assert list(counts.subjects_per_response) == sorted(counts.subjects_per_response)
    assert list(counts.subjects_per_sex) == sorted(counts.subjects_per_sex)
