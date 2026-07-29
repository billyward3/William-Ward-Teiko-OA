"""Tests for the end-to-end pipeline and the files it writes.

Two properties carry most of the weight here.

`outputs/` is committed, so a run that changes a byte is a defect: it dirties
the working tree on every `make pipeline`. The realistic ways that breaks are a
PNG text chunk naming the matplotlib that drew it and a CSV written with CRLF,
neither of which existence or size checks can see, so bytes are asserted.

The pipeline is the only place the spec's three different cohorts sit side by
side. Part 3 and Part 4 use melanoma / miraclib / PBMC / baseline; the form
question deliberately does not. The fixture contains a subject who is in one and
not the other, so reusing a cohort produces a different number rather than the
same one.

Every artifact is written under `tmp_path`. Nothing here touches the real
`outputs/`.
"""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

import pytest

import fixtures
from cellcount import pipeline
from cellcount.cohort import Cohort
from cellcount.comparison import ComparisonResult, compare
from cellcount.db import connect
from cellcount.loader import POPULATIONS, build_database
from cellcount.means import mean_count
from cellcount.pipeline import (
    BASELINE_COHORT,
    FORM_QUESTION_COHORT,
    FORM_QUESTION_POPULATION,
    TIMEPOINTS,
    Artifacts,
    run_pipeline,
    write_outputs,
)
from cellcount.plots import boxplot_figure, save_boxplot
from test_plots import texts as figure_texts


@pytest.fixture
def csv_path(tmp_path: Path) -> Path:
    path = tmp_path / "cell-count.csv"
    fixtures.write_csv(path)
    return path


@pytest.fixture
def artifacts(tmp_path: Path, csv_path: Path) -> Artifacts:
    return run_pipeline(
        csv_path=csv_path,
        db_path=tmp_path / "cell-count.db",
        outputs_dir=tmp_path / "outputs",
    )


@pytest.fixture
def loaded(tmp_path: Path, csv_path: Path) -> Iterable[sqlite3.Connection]:
    db_path = tmp_path / "loaded.db"
    build_database(csv_path, db_path)
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    return rows[0], rows[1:]


# --- the fixture itself -----------------------------------------------------


def test_no_two_fixture_samples_share_a_total() -> None:
    """Guards the property the percentage assertions below depend on."""
    totals = [
        sum(int(row[population]) for population in POPULATIONS)
        for row in fixtures.rows()
    ]
    assert len(set(totals)) == len(totals)


# --- artifacts --------------------------------------------------------------


def test_writes_every_expected_artifact(artifacts: Artifacts) -> None:
    for path in artifacts.paths:
        assert path.is_file(), f"{path.name} was not written"
        assert path.stat().st_size > 0, f"{path.name} is empty"


def test_creates_the_outputs_directory(tmp_path: Path, csv_path: Path) -> None:
    outputs = tmp_path / "nested" / "outputs"
    run_pipeline(
        csv_path=csv_path, db_path=tmp_path / "cell-count.db", outputs_dir=outputs
    )
    assert outputs.is_dir()


def test_every_artifact_lands_in_the_outputs_directory(
    tmp_path: Path, artifacts: Artifacts
) -> None:
    for path in artifacts.paths:
        assert path.parent == tmp_path / "outputs"


CSV_ARTIFACTS = ("summary", "comparison", "comparison_by_timepoint", "subsets")


def test_every_csv_uses_lf_line_endings(artifacts: Artifacts) -> None:
    """`csv` defaults to CRLF whatever the platform.

    The committed files would then differ from the ones a Unix grader
    regenerates, on every line, while still parsing identically. Deleting
    `lineterminator="\\n"` from the writer passes every other test here.
    """
    for name in CSV_ARTIFACTS:
        path: Path = getattr(artifacts, name)
        assert b"\r" not in path.read_bytes(), f"{path.name} has CR line endings"


def test_the_boxplot_carries_no_metadata_chunk(artifacts: Artifacts) -> None:
    """The committed figure must not depend on the grader's matplotlib version."""
    written = artifacts.boxplot.read_bytes()
    assert b"Matplotlib version" not in written
    for chunk in (b"tEXt", b"iTXt", b"zTXt", b"tIME"):
        assert chunk not in written, f"{chunk.decode()} chunk present"


def test_rerunning_produces_byte_identical_output(
    tmp_path: Path, csv_path: Path
) -> None:
    """`outputs/` is committed, so a second run must not dirty the tree.

    Two runs on one machine share a matplotlib and a platform, so this catches
    a wall-clock timestamp and little else; the two tests above cover what it
    cannot.
    """
    kwargs = {
        "csv_path": csv_path,
        "db_path": tmp_path / "cell-count.db",
        "outputs_dir": tmp_path / "outputs",
    }
    first = run_pipeline(**kwargs)
    before = {path.name: path.read_bytes() for path in first.paths}
    second = run_pipeline(**kwargs)
    after = {path.name: path.read_bytes() for path in second.paths}

    assert before.keys() == after.keys()
    differing = [name for name in before if before[name] != after[name]]
    assert not differing, f"not reproducible: {differing}"


def test_rerunning_replaces_stale_content(tmp_path: Path, csv_path: Path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    stale = outputs / "part2_summary.csv"
    stale.write_text("nonsense\n" * 500, encoding="utf-8")

    run_pipeline(
        csv_path=csv_path, db_path=tmp_path / "cell-count.db", outputs_dir=outputs
    )
    assert "nonsense" not in stale.read_text(encoding="utf-8")


def test_run_pipeline_builds_the_database_from_the_csv(
    tmp_path: Path, csv_path: Path
) -> None:
    db_path = tmp_path / "cell-count.db"
    assert not db_path.exists()

    run_pipeline(csv_path=csv_path, db_path=db_path, outputs_dir=tmp_path / "outputs")

    conn = connect(db_path)
    try:
        samples = conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    finally:
        conn.close()
    assert samples == len(fixtures.rows())


# --- Part 2 -----------------------------------------------------------------


def test_summary_csv_has_the_columns_the_spec_names(artifacts: Artifacts) -> None:
    header, _ = read_csv(artifacts.summary)
    assert header == ["sample", "total_count", "population", "count", "percentage"]


def test_summary_csv_covers_every_sample_and_population(
    artifacts: Artifacts,
) -> None:
    _, rows = read_csv(artifacts.summary)
    expected = fixtures.rows()
    assert len(rows) == len(expected) * len(POPULATIONS)
    assert {row[0] for row in rows} == {row["sample"] for row in expected}


def test_summary_csv_percentages_use_each_samples_own_total(
    artifacts: Artifacts,
) -> None:
    """No two fixture samples share a total, so a shared denominator shows up."""
    _, rows = read_csv(artifacts.summary)
    by_sample = {row["sample"]: row for row in fixtures.rows()}

    for sample, total_count, population, count, percentage in rows:
        source = by_sample[sample]
        expected_total = sum(int(source[p]) for p in POPULATIONS)
        assert int(total_count) == expected_total
        assert int(count) == int(source[population])
        assert float(percentage) == pytest.approx(
            100.0 * int(source[population]) / expected_total, abs=1e-5
        )


def test_summary_csv_is_not_restricted_to_the_part_3_cohort(
    artifacts: Artifacts,
) -> None:
    """Part 2 is "each sample", including the ones later parts filter out."""
    _, rows = read_csv(artifacts.summary)
    samples = {row[0] for row in rows}
    assert "sbj14-pbmc-t0" in samples  # carcinoma
    assert "sbj15-pbmc-t0" in samples  # healthy, no response
    assert "sbj08-wb-t0" in samples  # not PBMC


# --- Part 3 -----------------------------------------------------------------

COMPARISON_COLUMNS = [
    "population",
    "n_no",
    "n_yes",
    "median_no",
    "median_yes",
    "shift",
    "ci_low",
    "ci_high",
    # Both levels, so the headline's simultaneous bound is reproducible from a
    # committed file rather than only from the prose that quotes it.
    "simultaneous_ci_low",
    "simultaneous_ci_high",
    "p_value",
    "q_value",
    "effect_size",
]


def test_comparison_csv_has_a_row_per_population(artifacts: Artifacts) -> None:
    header, rows = read_csv(artifacts.comparison)
    assert header == COMPARISON_COLUMNS
    assert [row[0] for row in rows] == sorted(POPULATIONS)


def test_comparison_csv_reports_what_compare_returned(
    artifacts: Artifacts, loaded: sqlite3.Connection
) -> None:
    """The file must carry `compare`'s numbers, not a second computation."""
    result = compare(loaded, BASELINE_COHORT)
    expected = {p.population: p for p in result.populations}

    header, rows = read_csv(artifacts.comparison)
    assert rows, "no populations were written"
    # Keyed by column name, not position. Adding a column ahead of these used to
    # shift every index and reported a wrong value as a wrong number rather than
    # as a wrong lookup.
    for values in (dict(zip(header, row, strict=True)) for row in rows):
        population = expected[values["population"]]
        assert population.shift is not None
        assert population.shift_ci is not None
        assert population.simultaneous_ci is not None

        assert int(values["n_no"]) == population.n["no"]
        assert int(values["n_yes"]) == population.n["yes"]
        for column, want, tolerance in (
            ("median_no", population.median["no"], 1e-5),
            ("median_yes", population.median["yes"], 1e-5),
            ("shift", population.shift, 1e-5),
            ("ci_low", population.shift_ci[0], 1e-5),
            ("ci_high", population.shift_ci[1], 1e-5),
            ("simultaneous_ci_low", population.simultaneous_ci[0], 1e-5),
            ("simultaneous_ci_high", population.simultaneous_ci[1], 1e-5),
            ("p_value", population.p_value, 1e-9),
            ("q_value", population.q_value, 1e-9),
            ("effect_size", population.effect_size, 1e-9),
        ):
            assert float(values[column]) == pytest.approx(want, abs=tolerance), column


def test_comparison_csv_uses_the_baseline_cohort(artifacts: Artifacts) -> None:
    """7 non-responders and 5 responders, PBMC only, at t = 0."""
    _, rows = read_csv(artifacts.comparison)
    assert {int(row[1]) for row in rows} == {7}
    assert {int(row[2]) for row in rows} == {5}


def test_the_five_populations_get_five_distinct_p_values(
    artifacts: Artifacts,
) -> None:
    """Otherwise a writer pairing the wrong statistics with a population passes."""
    header, rows = read_csv(artifacts.comparison)
    column = header.index("p_value")
    assert len({row[column] for row in rows}) == len(POPULATIONS)


def test_timepoint_csv_covers_every_timepoint(artifacts: Artifacts) -> None:
    header, rows = read_csv(artifacts.comparison_by_timepoint)
    assert header == ["timepoint", *COMPARISON_COLUMNS]
    assert sorted({int(row[0]) for row in rows}) == sorted(TIMEPOINTS)
    for timepoint in TIMEPOINTS:
        at = [row for row in rows if int(row[0]) == timepoint]
        assert [row[1] for row in at] == sorted(POPULATIONS)


def test_timepoint_csv_corrects_within_each_timepoint(
    artifacts: Artifacts, loaded: sqlite3.Connection
) -> None:
    """BH across timepoints would give different q-values from BH within one."""
    header, rows = read_csv(artifacts.comparison_by_timepoint)
    q_column = header.index("q_value")
    name_column = header.index("population")
    for timepoint in TIMEPOINTS:
        result = compare(loaded, replace(BASELINE_COHORT, timepoints=(timepoint,)))
        expected = {p.population: p.q_value for p in result.populations}
        for row in rows:
            if int(row[0]) == timepoint:
                assert float(row[q_column]) == pytest.approx(
                    expected[row[name_column]], abs=1e-9
                )


def test_a_timepoint_with_only_one_response_group_is_skipped(
    tmp_path: Path,
) -> None:
    """A secondary view must not take the whole pipeline down."""
    rows = [row for row in fixtures.rows() if row["time_from_treatment_start"] != "7"]
    rows += [
        row
        for row in fixtures.rows()
        if row["time_from_treatment_start"] == "7" and row["response"] != "yes"
    ]
    path = tmp_path / "cell-count.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    artifacts = run_pipeline(
        csv_path=path,
        db_path=tmp_path / "cell-count.db",
        outputs_dir=tmp_path / "outputs",
    )
    _, written = read_csv(artifacts.comparison_by_timepoint)
    assert sorted({int(row[0]) for row in written}) == [0, 14]
    assert (
        "Timepoint 7 did not yield two response groups"
        in artifacts.findings.read_text(encoding="utf-8")
    )


def test_boxplot_is_a_png(artifacts: Artifacts) -> None:
    assert artifacts.boxplot.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_boxplot_draws_the_baseline_comparison(
    tmp_path: Path,
    csv_path: Path,
    loaded: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any timepoint's comparison renders an equally valid PNG.

    Magic bytes, size and byte-stability all pass on the t = 7 figure, so the
    file has to be checked for content that only baseline has: the baseline
    group sizes, 7 against 5, and the baseline q-values.
    """
    drawn: list[ComparisonResult] = []

    def spy(result: ComparisonResult, path: Path, **kwargs: str) -> None:
        drawn.append(result)
        save_boxplot(result, path, **kwargs)

    monkeypatch.setattr(pipeline, "save_boxplot", spy)
    run_pipeline(
        csv_path=csv_path,
        db_path=tmp_path / "cell-count.db",
        outputs_dir=tmp_path / "outputs",
    )

    assert len(drawn) == 1
    figure = boxplot_figure(drawn[0])
    try:
        rendered = figure_texts(figure)
    finally:
        figure.clear()

    assert "n = 7" in rendered
    assert "n = 5" in rendered
    expected = compare(loaded, BASELINE_COHORT)
    for population in expected.populations:
        assert population.q_value is not None
        assert f"q = {population.q_value:.3f}" in rendered


# --- Part 4 -----------------------------------------------------------------


def test_subset_csv_counts_samples_for_projects(artifacts: Artifacts) -> None:
    _, rows = read_csv(artifacts.subsets)
    projects = {row[1]: (row[2], int(row[3])) for row in rows if row[0] == "project"}
    assert projects == {
        "prj1": ("samples", 7),
        "prj2": ("samples", 0),
        "prj3": ("samples", 5),
    }


def test_subset_csv_counts_subjects_for_response_and_sex(
    artifacts: Artifacts,
) -> None:
    header, rows = read_csv(artifacts.subsets)
    assert header == ["breakdown", "category", "unit", "count"]
    by_breakdown = {
        breakdown: {
            row[1]: (row[2], int(row[3])) for row in rows if row[0] == breakdown
        }
        for breakdown in ("response", "sex")
    }
    assert by_breakdown["response"] == {
        "no": ("subjects", 7),
        "yes": ("subjects", 5),
    }
    assert by_breakdown["sex"] == {"F": ("subjects", 4), "M": ("subjects", 8)}


def test_subset_counts_exclude_the_other_sample_types_and_treatments(
    artifacts: Artifacts,
) -> None:
    """sbj13 is melanoma but on phauximab; sbj08 has a WB sample at t = 0."""
    _, rows = read_csv(artifacts.subsets)
    total_samples = sum(int(row[3]) for row in rows if row[0] == "project")
    assert total_samples == 12


# --- the form question ------------------------------------------------------


def test_form_answer_reports_the_mean_to_two_decimals(
    artifacts: Artifacts, loaded: sqlite3.Connection
) -> None:
    expected = mean_count(loaded, FORM_QUESTION_COHORT, FORM_QUESTION_POPULATION)
    assert expected is not None
    text = artifacts.form_answer.read_text(encoding="utf-8")
    assert f"{expected:.2f}" in text


def test_form_answer_spans_every_sample_type_and_treatment(
    artifacts: Artifacts,
) -> None:
    """The cohort is looser than Part 4's, which is the trap the question sets.

    sbj08 contributes a WB sample as well as a PBMC one, and sbj13 is on
    phauximab. Both count here and neither counts in Part 4.
    """
    expected = [
        int(row["b_cell"])
        for row in fixtures.rows()
        if row["condition"] == "melanoma"
        and row["sex"] == "M"
        and row["response"] == "yes"
        and row["time_from_treatment_start"] == "0"
    ]
    assert len(expected) == 5  # four subjects, one of them sampled twice

    text = artifacts.form_answer.read_text(encoding="utf-8")
    assert f"{sum(expected) / len(expected):.2f}" in text


def test_form_answer_differs_from_the_part_4_cohort(
    loaded: sqlite3.Connection,
) -> None:
    """Reusing Part 4's filter is confidently wrong, so pin the difference."""
    from dataclasses import replace

    part4_style = replace(BASELINE_COHORT, sex="M", response="yes")
    assert mean_count(loaded, part4_style, FORM_QUESTION_POPULATION) != mean_count(
        loaded, FORM_QUESTION_COHORT, FORM_QUESTION_POPULATION
    )


def test_form_answer_states_how_many_samples_and_subjects_it_averaged(
    artifacts: Artifacts,
) -> None:
    """Five samples from four subjects, because sbj08 is sampled twice at t = 0.

    The two counts differ here on purpose. In the delivered data they coincide
    at 485, so only this fixture can tell a subject count from a sample count.
    """
    text = artifacts.form_answer.read_text(encoding="utf-8")
    assert "5 samples" in text
    assert "4 subjects" in text


# --- findings ---------------------------------------------------------------


def test_findings_is_markdown_naming_the_cohort_and_the_bound(
    artifacts: Artifacts,
) -> None:
    text = artifacts.findings.read_text(encoding="utf-8")
    assert text.startswith("#")
    for token in ("melanoma", "miraclib", "PBMC", "baseline"):
        assert token in text


def test_findings_reflect_a_planted_difference(tmp_path: Path) -> None:
    """The document is generated, so it must not hardcode the null conclusion."""
    path = tmp_path / "cell-count.csv"
    fixtures.write_csv(path, b_cell_shift=fixtures.B_CELL_SHIFT)
    artifacts = run_pipeline(
        csv_path=path,
        db_path=tmp_path / "cell-count.db",
        outputs_dir=tmp_path / "outputs",
    )
    text = artifacts.findings.read_text(encoding="utf-8")
    assert "b_cell" in text
    assert "no population differs significantly" not in text.lower()


# --- writing to an existing connection --------------------------------------


def test_write_outputs_needs_no_load_step(
    tmp_path: Path, loaded: sqlite3.Connection
) -> None:
    """The artifact writer takes a connection, so the API can reuse it."""
    outputs = tmp_path / "outputs"
    artifacts = write_outputs(loaded, outputs)
    assert all(path.is_file() for path in artifacts.paths)


def test_an_empty_database_produces_artifacts_rather_than_an_exception(
    tmp_path: Path,
) -> None:
    from cellcount.db import create_schema

    conn = connect(tmp_path / "empty.db")
    try:
        create_schema(conn)
        artifacts = write_outputs(conn, tmp_path / "outputs")
    finally:
        conn.close()
    assert all(path.is_file() for path in artifacts.paths)


def test_cohorts_match_the_spec() -> None:
    parts_3_and_4 = Cohort(
        condition="melanoma",
        treatment="miraclib",
        sample_type="PBMC",
        timepoints=(0,),
    )
    form_question = Cohort(
        condition="melanoma", response="yes", sex="M", timepoints=(0,)
    )
    assert parts_3_and_4 == BASELINE_COHORT
    assert form_question == FORM_QUESTION_COHORT
    assert FORM_QUESTION_POPULATION == "b_cell"
