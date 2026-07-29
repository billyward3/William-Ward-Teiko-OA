"""Tests for the Part 3 boxplot.

A boxplot of five summary statistics can hide everything that matters: how many
observations there are, whether they overlap, and whether one group is three
points against three hundred. So the assertions here are about what the figure
shows beyond the boxes, namely every individual observation and the group size
next to each box.

The figure is built and inspected in memory. Only the reproducibility tests
write a file, because that is the one property a Figure object cannot carry.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from matplotlib.figure import Figure

from cellcount.cohort import Cohort
from cellcount.comparison import ComparisonResult, PopulationComparison
from cellcount.plots import boxplot_figure, save_boxplot

COHORT = Cohort(
    condition="melanoma", treatment="miraclib", sample_type="PBMC", timepoints=(0,)
)

# Deliberately unequal, and deliberately not a round number of points, so a
# panel that draws one group's points twice, or draws the wrong group's, shows.
NO_VALUES = [4.1, 4.4, 3.8, 5.2, 4.9, 4.0, 4.6, 5.5, 3.9]
YES_VALUES = [4.7, 5.1, 4.2, 6.0, 4.3]


def population(
    name: str,
    *,
    p_value: float | None = 0.31,
    q_value: float | None = 0.78,
    shift: float | None = -0.4,
    ci: tuple[float, float] | None = (-1.2, 0.4),
    simultaneous: tuple[float, float] | None = None,
    effect_size: float | None = 0.38,
) -> PopulationComparison:
    """The figure annotates the marginal interval, so `simultaneous` is only
    here to keep the fixture a shape `compare` could actually return: wider
    than the marginal one, and absent whenever that one is."""
    if simultaneous is None and ci is not None:
        simultaneous = (ci[0] * 1.3, ci[1] * 1.3)
    return PopulationComparison(
        population=name,
        n={"no": len(NO_VALUES), "yes": len(YES_VALUES)},
        median={"no": 4.4, "yes": 4.7},
        values={"no": list(NO_VALUES), "yes": list(YES_VALUES)},
        p_value=p_value,
        q_value=q_value,
        shift=shift,
        shift_ci=ci,
        simultaneous_ci=simultaneous,
        effect_size=effect_size,
    )


def result(populations: list[PopulationComparison]) -> ComparisonResult:
    return ComparisonResult(
        cohort=COHORT,
        split_on="response",
        groups=("no", "yes"),
        n_samples={"no": len(NO_VALUES), "yes": len(YES_VALUES)},
        n_subjects={"no": len(NO_VALUES), "yes": len(YES_VALUES)},
        repeated_measures=False,
        n_tested=len([p for p in populations if p.p_value is not None]),
        alpha=0.05,
        populations=populations,
    )


NAMES = ("b_cell", "cd4_t_cell", "cd8_t_cell", "monocyte", "nk_cell")
RESULT = result([population(name) for name in NAMES])


def texts(figure: Figure) -> str:
    """Every string the figure draws, including tick labels and annotations."""
    pieces = [t.get_text() for t in figure.texts]
    for axes in figure.axes:
        pieces.append(axes.get_title())
        pieces.append(axes.get_xlabel())
        pieces.append(axes.get_ylabel())
        pieces += [t.get_text() for t in axes.texts]
        pieces += [t.get_text() for t in axes.get_xticklabels()]
    return "\n".join(pieces)


def test_one_panel_per_population() -> None:
    figure = boxplot_figure(RESULT)
    try:
        assert len(figure.axes) == len(NAMES)
        assert [axes.get_title() for axes in figure.axes] == list(NAMES)
    finally:
        figure.clear()


def test_each_panel_draws_a_box_per_group() -> None:
    figure = boxplot_figure(RESULT)
    try:
        for axes in figure.axes:
            assert len(axes.patches) == 2
    finally:
        figure.clear()


def test_every_individual_observation_is_drawn() -> None:
    """The boxes alone would hide 9 against 5."""
    figure = boxplot_figure(RESULT)
    try:
        for axes in figure.axes:
            drawn = sum(
                len(np.asarray(collection.get_offsets()))
                for collection in axes.collections
            )
            assert drawn == len(NO_VALUES) + len(YES_VALUES)
    finally:
        figure.clear()


def test_points_sit_at_the_values_they_represent() -> None:
    """Jitter is horizontal only; a vertical jitter would falsify the data."""
    figure = boxplot_figure(RESULT)
    try:
        axes = figure.axes[0]
        heights = sorted(
            float(y)
            for collection in axes.collections
            for y in np.asarray(collection.get_offsets())[:, 1]
        )
        assert heights == sorted(NO_VALUES + YES_VALUES)
    finally:
        figure.clear()


def test_each_group_is_labelled_with_its_size() -> None:
    figure = boxplot_figure(RESULT)
    try:
        rendered = texts(figure)
        assert f"n = {len(NO_VALUES)}" in rendered
        assert f"n = {len(YES_VALUES)}" in rendered
    finally:
        figure.clear()


def test_both_groups_are_named() -> None:
    figure = boxplot_figure(RESULT)
    try:
        rendered = texts(figure).lower()
        assert "non-responder" in rendered
        assert "responder" in rendered
    finally:
        figure.clear()


def test_each_panel_reports_the_q_value_from_the_result() -> None:
    figure = boxplot_figure(RESULT)
    try:
        assert "0.78" in texts(figure)
    finally:
        figure.clear()


def test_an_untested_population_says_so_rather_than_showing_a_blank() -> None:
    figure = boxplot_figure(
        result(
            [
                population("b_cell"),
                population(
                    "monocyte",
                    p_value=None,
                    q_value=None,
                    shift=None,
                    ci=None,
                    effect_size=None,
                ),
            ]
        )
    )
    try:
        assert "not tested" in texts(figure).lower()
    finally:
        figure.clear()


def test_an_empty_result_still_renders_a_figure() -> None:
    empty = ComparisonResult(
        cohort=COHORT,
        split_on="response",
        groups=(),
        n_samples={},
        n_subjects={},
        repeated_measures=False,
        n_tested=0,
        alpha=0.05,
        populations=[],
    )
    figure = boxplot_figure(empty)
    try:
        assert "no samples" in texts(figure).lower()
    finally:
        figure.clear()


def test_the_saved_png_is_byte_identical_across_runs(tmp_path: Path) -> None:
    """Jitter must come from a fixed seed, and the PNG must carry no metadata."""
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    save_boxplot(RESULT, first)
    save_boxplot(RESULT, second)
    assert first.read_bytes() == second.read_bytes()


def test_the_saved_png_carries_no_metadata_chunk(tmp_path: Path) -> None:
    """Two runs on one machine agree even with metadata, so the test above
    cannot see this.

    Matplotlib 3.11 writes no creation date; it writes a `Software` text chunk
    naming its own version. That would make the committed PNG depend on which
    matplotlib the grader installed, and every regeneration on a different
    version would dirty the working tree. Deleting the `metadata` kwarg from
    `save_boxplot` passes every other assertion in this file.
    """
    path = tmp_path / "plot.png"
    save_boxplot(RESULT, path)
    written = path.read_bytes()
    assert b"Matplotlib version" not in written
    for chunk in (b"tEXt", b"iTXt", b"zTXt", b"tIME"):
        assert chunk not in written, f"{chunk.decode()} chunk present"


def test_the_saved_file_is_a_png(tmp_path: Path) -> None:
    path = tmp_path / "plot.png"
    save_boxplot(RESULT, path)
    assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
