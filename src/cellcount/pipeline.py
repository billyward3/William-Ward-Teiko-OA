"""One command that rebuilds the database and writes every output artifact.

`make pipeline` runs this. It is the only place the spec's three cohorts sit
side by side, which is deliberate: Part 3 and Part 4 share one filter, and the
form question uses a looser one that happens to answer a different question. A
reader can see all three here rather than inferring them.

Artifacts land in `outputs/`, which is committed, so writing must be
reproducible. Running the pipeline twice has to leave the working tree
unchanged: floats are formatted to a fixed precision, rows come out of SQL in a
fixed order, CSVs are written with LF line endings whatever the platform, and
the figure carries no metadata chunk naming the matplotlib that drew it.

`compare` is the expensive call, so the baseline comparison is computed once and
used both as the headline and as the t = 0 row of the per-timepoint panel.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from cellcount.cohort import ALL_SAMPLES, Cohort, conditions, render_where
from cellcount.comparison import ComparisonResult, NotTwoGroups, compare
from cellcount.db import connect
from cellcount.findings import findings_markdown
from cellcount.loader import build_database
from cellcount.means import mean_count
from cellcount.plots import save_boxplot
from cellcount.subsets import subset_counts
from cellcount.summary import summary_page

# Parts 3 and 4 share this filter. Part 4 states it; Part 3 arrives at the same
# place for a different reason, which the findings document explains.
MELANOMA_MIRACLIB_PBMC = Cohort(
    condition="melanoma", treatment="miraclib", sample_type="PBMC"
)

BASELINE_TIMEPOINT = 0
TIMEPOINTS = (0, 7, 14)

BASELINE_COHORT = replace(MELANOMA_MIRACLIB_PBMC, timepoints=(BASELINE_TIMEPOINT,))

# The submission form asks about melanoma males across *all* sample types and
# *all* treatments, and about an absolute count rather than a frequency.
# Reusing the cohort above produces a different number, confidently.
FORM_QUESTION = (
    "Considering melanoma males of all sample and treatment types, what is "
    "the average number of B cells for responders at time = 0?"
)
FORM_QUESTION_COHORT = Cohort(
    condition="melanoma", response="yes", sex="M", timepoints=(BASELINE_TIMEPOINT,)
)
FORM_QUESTION_POPULATION = "b_cell"

_FILENAMES = {
    "summary": "part2_summary.csv",
    "comparison": "part3_comparison_baseline.csv",
    "comparison_by_timepoint": "part3_comparison_by_timepoint.csv",
    "boxplot": "part3_boxplot_baseline.png",
    "subsets": "part4_subsets.csv",
    "form_answer": "form_answer.md",
    "findings": "findings.md",
}

SUMMARY_COLUMNS = ("sample", "total_count", "population", "count", "percentage")
"""Fixed by the spec, so these names are a contract rather than a choice."""

SUBSET_COLUMNS = ("breakdown", "category", "unit", "count")
"""`unit` carries the grain, which differs by row: the spec counts samples per
project but *subjects* per response and per sex."""

# Both interval levels are written. The marginal pair is what the results table
# quotes per population; the simultaneous pair is what the headline's "any shift
# larger than" is entitled to, and without it that number could not be
# reproduced from any committed file.
_STAT_COLUMNS = (
    "shift",
    "ci_low",
    "ci_high",
    "simultaneous_ci_low",
    "simultaneous_ci_high",
    "p_value",
    "q_value",
    "effect_size",
)

# Column names carry the group they describe, which needs two group names. An
# empty comparison has none, so the header falls back to placeholders and the
# file is written with no rows rather than not written at all.
_PLACEHOLDER_GROUPS = ("group_1", "group_2")


@dataclass(frozen=True)
class Artifacts:
    """Where each output landed. Named fields, so a caller cannot mix two up."""

    summary: Path
    comparison: Path
    comparison_by_timepoint: Path
    boxplot: Path
    subsets: Path
    form_answer: Path
    findings: Path

    @property
    def paths(self) -> tuple[Path, ...]:
        return (
            self.summary,
            self.comparison,
            self.comparison_by_timepoint,
            self.boxplot,
            self.subsets,
            self.form_answer,
            self.findings,
        )

    @classmethod
    def under(cls, directory: Path) -> Artifacts:
        return cls(**{name: directory / file for name, file in _FILENAMES.items()})


@dataclass(frozen=True)
class CohortSize:
    samples: int
    subjects: int


_COHORT_SIZE_SQL = """
SELECT COUNT(*), COUNT(DISTINCT samples.subject_id)
FROM samples
JOIN subjects USING (subject_id)
"""


def cohort_size(conn: sqlite3.Connection, cohort: Cohort) -> CohortSize:
    """How many samples and how many distinct subjects a cohort covers.

    Reported together because they can differ, and a mean over samples reads
    differently once you know how many subjects those samples came from.
    """
    fragments, params = conditions(cohort)
    samples, subjects = conn.execute(
        _COHORT_SIZE_SQL + render_where(fragments), params
    ).fetchone()
    return CohortSize(samples=samples, subjects=subjects)


# --- formatting -------------------------------------------------------------


def _pp(value: float | None) -> str:
    """A quantity in percentage points. Six decimals is far past the precision
    of counts that are whole numbers, and keeps the file stable between runs."""
    return "" if value is None else f"{value + 0.0:.6f}"


def _stat(value: float | None) -> str:
    """A p-value, q-value or effect size, at enough digits to round-trip usefully."""
    return "" if value is None else f"{value + 0.0:.10g}"


def _write_csv(
    path: Path, header: Sequence[str], rows: Iterable[Sequence[object]]
) -> None:
    # `lineterminator` is set because csv defaults to CRLF, which would make the
    # committed files differ from the ones a Unix grader regenerates.
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


# --- Part 2 -----------------------------------------------------------------


def _write_summary(conn: sqlite3.Connection, path: Path) -> None:
    page = summary_page(conn, ALL_SAMPLES)
    _write_csv(
        path,
        SUMMARY_COLUMNS,
        (
            (
                row.sample,
                row.total_count,
                row.population,
                row.count,
                _pp(row.percentage),
            )
            for row in page.rows
        ),
    )


# --- Part 3 -----------------------------------------------------------------


def _comparison_header(result: ComparisonResult) -> list[str]:
    first, second = result.groups if len(result.groups) == 2 else _PLACEHOLDER_GROUPS
    return [
        "population",
        f"n_{first}",
        f"n_{second}",
        f"median_{first}",
        f"median_{second}",
        *_STAT_COLUMNS,
    ]


def _comparison_rows(result: ComparisonResult) -> Iterator[list[str]]:
    if len(result.groups) != 2:
        return
    first, second = result.groups
    for comparison in result.populations:
        low, high = comparison.shift_ci or (None, None)
        joint_low, joint_high = comparison.simultaneous_ci or (None, None)
        yield [
            comparison.population,
            str(comparison.n[first]),
            str(comparison.n[second]),
            _pp(comparison.median[first]),
            _pp(comparison.median[second]),
            _pp(comparison.shift),
            _pp(low),
            _pp(high),
            _pp(joint_low),
            _pp(joint_high),
            _stat(comparison.p_value),
            _stat(comparison.q_value),
            _stat(comparison.effect_size),
        ]


def _write_comparison(result: ComparisonResult, path: Path) -> None:
    _write_csv(path, _comparison_header(result), _comparison_rows(result))


def _write_comparison_by_timepoint(
    baseline: ComparisonResult,
    by_timepoint: Sequence[tuple[int, ComparisonResult]],
    path: Path,
) -> None:
    """One block of rows per timepoint, each already corrected within itself.

    A timepoint whose groups differ from the headline's would not fit these
    columns, so it is left out rather than written under a header that misnames
    it. The findings document reports which timepoints are missing.
    """
    header = ["timepoint", *_comparison_header(baseline)]
    rows = [
        [str(timepoint), *row]
        for timepoint, result in by_timepoint
        if result.groups == baseline.groups
        for row in _comparison_rows(result)
    ]
    _write_csv(path, header, rows)


def _boxplot_subtitle(result: ComparisonResult) -> str:
    return (
        f"Mann-Whitney U, Benjamini-Hochberg across {result.n_tested} "
        f"populations, alpha = {result.alpha:g}. Each point is one sample."
    )


# --- Part 4 -----------------------------------------------------------------


def _write_subsets(conn: sqlite3.Connection, path: Path) -> None:
    counts = subset_counts(conn, BASELINE_COHORT)
    rows = [
        *(
            ("project", project, "samples", count)
            for project, count in counts.samples_per_project.items()
        ),
        *(
            ("response", response, "subjects", count)
            for response, count in counts.subjects_per_response.items()
        ),
        *(
            ("sex", sex, "subjects", count)
            for sex, count in counts.subjects_per_sex.items()
        ),
    ]
    _write_csv(path, SUBSET_COLUMNS, rows)


# --- the form question ------------------------------------------------------


def _form_answer_markdown(conn: sqlite3.Connection) -> str:
    mean = mean_count(conn, FORM_QUESTION_COHORT, FORM_QUESTION_POPULATION)
    size = cohort_size(conn, FORM_QUESTION_COHORT)

    lines = [
        "# Form question",
        "",
        f"> {FORM_QUESTION}",
        "",
        "**No samples matched, so there is no answer to give.**"
        if mean is None
        else f"**{mean:.2f}**",
        "",
        "## How that was computed",
        "",
        f"The arithmetic mean of the absolute `{FORM_QUESTION_POPULATION}` "
        "count over every sample with `condition = melanoma`, `sex = M`, "
        "`response = yes` and `time_from_treatment_start = 0`.",
        f"{size.samples:,} samples, from {size.subjects:,} subjects.",
        "",
        "Treatment and sample type are deliberately unconstrained.",
        "That makes this cohort wider than Part 4's, which fixes "
        "`treatment = miraclib` and `sample_type = PBMC`, and reusing Part 4's "
        "filter here returns a different number.",
        "",
        "The answer is an absolute count, not the relative frequency Part 2 reports.",
        "",
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


# --- orchestration ----------------------------------------------------------


def _comparisons(
    conn: sqlite3.Connection,
) -> tuple[ComparisonResult, list[tuple[int, ComparisonResult]], list[int]]:
    """The headline comparison, the per-timepoint panel, and what was skipped.

    The baseline result is computed once and reused as the t = 0 row: `compare`
    walks every pairwise difference, which is the slowest thing the pipeline
    does, and running it twice on the same cohort would be pure waste.

    A timepoint that does not yield two groups is recorded and skipped. The
    headline is not treated that way: if the cohort the whole report is about
    cannot be compared, that is worth failing on.
    """
    baseline = compare(conn, BASELINE_COHORT)
    by_timepoint: list[tuple[int, ComparisonResult]] = []
    skipped: list[int] = []

    for timepoint in TIMEPOINTS:
        if timepoint == BASELINE_TIMEPOINT:
            by_timepoint.append((timepoint, baseline))
            continue
        cohort = replace(MELANOMA_MIRACLIB_PBMC, timepoints=(timepoint,))
        try:
            by_timepoint.append((timepoint, compare(conn, cohort)))
        except NotTwoGroups:
            skipped.append(timepoint)

    return baseline, by_timepoint, skipped


def write_outputs(conn: sqlite3.Connection, outputs_dir: Path) -> Artifacts:
    """Write every artifact into `outputs_dir`, creating it if needed.

    Takes a connection rather than a path so the same code can serve a caller
    that already has one open.
    """
    outputs_dir.mkdir(parents=True, exist_ok=True)
    artifacts = Artifacts.under(outputs_dir)

    _write_summary(conn, artifacts.summary)

    baseline, by_timepoint, skipped = _comparisons(conn)
    _write_comparison(baseline, artifacts.comparison)
    _write_comparison_by_timepoint(
        baseline, by_timepoint, artifacts.comparison_by_timepoint
    )
    save_boxplot(
        baseline,
        artifacts.boxplot,
        title="Relative frequency by response: melanoma, miraclib, PBMC, baseline",
        subtitle=_boxplot_subtitle(baseline),
    )

    _write_subsets(conn, artifacts.subsets)
    artifacts.form_answer.write_text(_form_answer_markdown(conn), encoding="utf-8")
    artifacts.findings.write_text(
        findings_markdown(baseline, by_timepoint, skipped_timepoints=skipped),
        encoding="utf-8",
    )
    return artifacts


def run_pipeline(*, csv_path: Path, db_path: Path, outputs_dir: Path) -> Artifacts:
    """Rebuild the database from the CSV, then write every artifact.

    This is the whole of `make pipeline`. The database is rebuilt rather than
    updated, so the run does not depend on what was there before.
    """
    build_database(csv_path, db_path)
    conn = connect(db_path)
    try:
        return write_outputs(conn, outputs_dir)
    finally:
        conn.close()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Load cell-count.csv and write every output artifact. "
            "Paths default to the repository layout, so it takes no arguments "
            "when run from the repository root."
        )
    )
    parser.add_argument("--csv", type=Path, default=Path("cell-count.csv"))
    parser.add_argument("--database", type=Path, default=Path("cell-count.db"))
    parser.add_argument("--outputs", type=Path, default=Path("outputs"))
    args = parser.parse_args(argv)

    artifacts = run_pipeline(
        csv_path=args.csv, db_path=args.database, outputs_dir=args.outputs
    )
    print(f"Loaded {args.csv} -> {args.database}")
    print(f"Wrote {len(artifacts.paths)} artifacts:")
    for path in artifacts.paths:
        print(f"  {path}")


if __name__ == "__main__":
    main()
