"""Characterization tests: the answers this submission actually reports.

Every other test in the suite runs on synthetic fixtures, which is what keeps
them fast and their failures diagnostic. These do the opposite on purpose. They
run the real pipeline over the real `cell-count.csv` and pin the numbers that
get graded, so a refactor that quietly changes an answer fails here rather than
in a reviewer's spreadsheet.

The values were derived independently of this code before it was written.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from cellcount.loader import POPULATIONS
from cellcount.pipeline import Artifacts, run_pipeline


@pytest.fixture(scope="session")
def real_outputs(
    tmp_path_factory: pytest.TempPathFactory, cell_count_csv: Path
) -> Artifacts:
    """The whole pipeline, once, into a throwaway directory."""
    root = tmp_path_factory.mktemp("real")
    return run_pipeline(
        csv_path=cell_count_csv,
        db_path=root / "cell-count.db",
        outputs_dir=root / "outputs",
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_form_question_answer(real_outputs: Artifacts) -> None:
    """Melanoma males, responders, t = 0, every sample type and treatment."""
    text = real_outputs.form_answer.read_text(encoding="utf-8")
    assert "**10206.15**" in text
    assert "485 samples" in text
    # The two coincide here, so this pins the answer without discriminating a
    # sample count from a subject count. The pipeline fixture does that.
    assert "485 subjects" in text


def test_part_4_sample_and_subject_counts(real_outputs: Artifacts) -> None:
    rows = read_csv(real_outputs.subsets)
    counts = {(row["breakdown"], row["category"]): int(row["count"]) for row in rows}
    assert counts[("project", "prj1")] == 384
    assert counts[("project", "prj2")] == 0
    assert counts[("project", "prj3")] == 272
    assert counts[("response", "no")] == 325
    assert counts[("response", "yes")] == 331
    assert counts[("sex", "F")] == 312
    assert counts[("sex", "M")] == 344


def test_part_4_units_are_not_interchangeable(real_outputs: Artifacts) -> None:
    """656 samples but 656 subjects, since each contributes one at baseline.

    The two coincide in this dataset, which is exactly why the file records
    which unit each row is counted in.
    """
    rows = read_csv(real_outputs.subsets)
    units = {row["breakdown"]: row["unit"] for row in rows}
    assert units == {"project": "samples", "response": "subjects", "sex": "subjects"}


def test_part_3_baseline_finds_nothing_and_bounds_it(real_outputs: Artifacts) -> None:
    rows = read_csv(real_outputs.comparison)
    assert [row["population"] for row in rows] == sorted(POPULATIONS)

    for row in rows:
        assert int(row["n_no"]) == 325
        assert int(row["n_yes"]) == 331
        assert float(row["q_value"]) == pytest.approx(0.885, abs=0.001)
        low, high = float(row["ci_low"]), float(row["ci_high"])
        assert low < 0.0 < high, f"{row['population']} interval excludes zero"
        assert max(abs(low), abs(high)) < 1.1, f"{row['population']} bound too wide"


def test_findings_state_both_bounds_and_say_which_is_which(
    real_outputs: Artifacts,
) -> None:
    """The headline quantifies over populations, so it carries the joint level.

    1.10 is the widest marginal interval, monocyte's, and holds for monocyte
    alone. 1.32 is the same interval at alpha / 5, and is what "no population
    shifts by more than this" is entitled to claim at 95%.
    """
    text = real_outputs.findings.read_text(encoding="utf-8").lower()
    assert "no population differs significantly" in text
    assert "1.10 percentage points" in text
    assert "1.32 percentage points" in text
    headline = text.split("## cohort")[0]
    assert "1.32 percentage points" in headline
    assert "simultaneous" in headline
    assert "1.10" not in headline
    # 1.32 / 19.95, to one decimal place. Rounding a ratio to no decimals makes
    # it disagree with what a reader recomputes from the two numbers printed
    # beside it as soon as the true value sits near a boundary, which the
    # marginal bound's 5.494 against a recomputed 5.514 did: "5" against "6".
    assert "about 6.6% of the population's own frequency" in text


def test_findings_check_the_correction_under_arbitrary_dependence(
    real_outputs: Artifacts,
) -> None:
    """Closure makes the five frequencies negatively correlated, so
    Benjamini-Hochberg's dependence condition is not established here.

    All five baseline p-values sit far from alpha, so Benjamini-Yekutieli
    saturates at 1.000; the smallest anywhere in the document is 0.165, at
    t = 14. Neither correction reaches alpha, which is the point.
    """
    text = real_outputs.findings.read_text(encoding="utf-8")
    assert "negatively correlated" in text
    assert "Benjamini-Yekutieli" in text
    assert "moves from 0.885 to 1.000" in text
    assert "0.165, at t = 14" in text
    assert "No q-value reaches alpha = 0.05 under either correction" in text


def test_summary_table_covers_every_sample(real_outputs: Artifacts) -> None:
    rows = read_csv(real_outputs.summary)
    assert len(rows) == 10_500 * len(POPULATIONS)
    assert len({row["sample"] for row in rows}) == 10_500
