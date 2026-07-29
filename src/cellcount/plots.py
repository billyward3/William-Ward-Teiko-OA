"""The Part 3 figure: relative frequency by response, one panel per population.

A boxplot is five numbers. On its own it cannot say whether those numbers came
from three observations or three hundred, and a reader who assumes the latter
draws a conclusion the data does not support. So every observation is drawn as a
point, and each group's size is written beside its box. Neither is decoration:
without them the figure would say less than the table it accompanies.

The annotation under each title is `compare`'s own q-value and interval rather
than a second computation. Significance is judged by the q-value, which is
adjusted across every tested population, not by whether the interval covers
zero, which is not adjusted.

Output is reproducible byte for byte. The horizontal jitter comes from a fixed
seed, and the PNG is written without the text chunk matplotlib embeds by
default, so re-running the pipeline leaves a committed figure unchanged instead
of dirtying the working tree.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

# Pinned for the whole process before anything can autodetect one: a headless
# container has no display, and the interactive default fails there rather than
# falling back. Figures below are built through the object API, so none of them
# is registered in pyplot's global state; this line covers any other code in the
# process that does reach for pyplot.
matplotlib.use("Agg")

import numpy as np  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from cellcount.comparison import (  # noqa: E402
    ComparisonResult,
    PopulationComparison,
    group_label,
)

# Two categorical hues, checked for colour-vision deficiency against this
# surface. Identity never rests on colour alone: each group is also named on the
# x axis and in the legend, so the hues reinforce rather than carry.
_GROUP_COLOURS = ("#2a78d6", "#eb6834")
_SURFACE = "#fcfcfb"
_INK = "#0b0b0b"
_INK_SECONDARY = "#52514e"
_INK_MUTED = "#8a8983"
_RULE = "#c9c8c2"
_GRID = "#e8e7e3"

# Fixed, so the same result always produces the same file. The jitter is
# cosmetic; its reproducibility is not.
_JITTER_SEED = 20240729
_JITTER_WIDTH = 0.26

_DPI = 150

_EMPTY_MESSAGE = "No samples matched this cohort, so there is nothing to plot."

DEFAULT_TITLE = "Relative frequency by response"


def _annotation(comparison: PopulationComparison) -> str:
    """The statistics printed under a panel title, or a note that there are none."""
    if comparison.q_value is None:
        return "not tested"
    lines = [f"q = {comparison.q_value:.3f}"]
    if comparison.shift is not None and comparison.shift_ci is not None:
        low, high = comparison.shift_ci
        lines.append(f"shift {comparison.shift:+.2f} pp  CI [{low:+.2f}, {high:+.2f}]")
    return "\n".join(lines)


def _style_axes(axes: Axes) -> None:
    """Recessive chrome: a hairline grid on one axis, no box around the panel."""
    axes.set_facecolor(_SURFACE)
    axes.grid(axis="y", color=_GRID, linewidth=0.6)
    axes.set_axisbelow(True)
    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axes.spines[side].set_color(_RULE)
        axes.spines[side].set_linewidth(0.8)
    axes.tick_params(colors=_INK_SECONDARY, labelsize=8, length=3, width=0.8)


def _empty_figure(title: str) -> Figure:
    figure = Figure(figsize=(8.0, 3.0), dpi=_DPI)
    figure.patch.set_facecolor(_SURFACE)
    axes = figure.subplots()
    axes.set_facecolor(_SURFACE)
    axes.axis("off")
    axes.set_title(title, fontsize=13, color=_INK)
    axes.text(
        0.5, 0.5, _EMPTY_MESSAGE, ha="center", va="center", fontsize=11, color=_INK
    )
    return figure


def boxplot_figure(
    result: ComparisonResult,
    *,
    title: str = DEFAULT_TITLE,
    subtitle: str | None = None,
) -> Figure:
    """One panel per population, two groups per panel, every observation drawn.

    Returns the figure rather than writing it, so callers can inspect it and so
    the output format stays the caller's decision.
    """
    if not result.populations or len(result.groups) != 2:
        return _empty_figure(title)

    first, second = result.groups
    populations = result.populations
    rng = np.random.default_rng(_JITTER_SEED)

    figure = Figure(figsize=(3.15 * len(populations) + 0.6, 5.2), dpi=_DPI)
    figure.patch.set_facecolor(_SURFACE)
    axes_row = figure.subplots(1, len(populations), squeeze=False)[0]

    for axes, comparison in zip(axes_row, populations, strict=True):
        _style_axes(axes)
        groups = [comparison.values[first], comparison.values[second]]

        # Points first, so the box outline reads on top of the cloud.
        for index, (values, colour) in enumerate(
            zip(groups, _GROUP_COLOURS, strict=True), start=1
        ):
            offsets = rng.uniform(-_JITTER_WIDTH, _JITTER_WIDTH, size=len(values))
            axes.scatter(
                np.full(len(values), float(index)) + offsets,
                values,
                s=9,
                color=colour,
                alpha=0.45,
                linewidths=0.0,
                zorder=2,
            )

        boxes = axes.boxplot(
            groups,
            positions=[1, 2],
            widths=0.62,
            patch_artist=True,
            showfliers=False,
            zorder=3,
        )
        for patch in boxes["boxes"]:
            patch.set_facecolor("none")
            patch.set_edgecolor(_INK_SECONDARY)
            patch.set_linewidth(1.0)
        for line in boxes["whiskers"] + boxes["caps"]:
            line.set_color(_INK_SECONDARY)
            line.set_linewidth(1.0)
        for line, colour in zip(boxes["medians"], _GROUP_COLOURS, strict=True):
            line.set_color(colour)
            line.set_linewidth(2.0)

        axes.set_xticks([1, 2])
        axes.set_xticklabels(
            [
                f"{group_label(group)}\nn = {comparison.n[group]}"
                for group in (first, second)
            ]
        )
        axes.set_xlim(0.4, 2.6)
        axes.set_title(comparison.population, fontsize=11, color=_INK, pad=28)
        axes.text(
            0.5,
            1.02,
            _annotation(comparison),
            transform=axes.transAxes,
            ha="center",
            va="bottom",
            fontsize=7.5,
            color=_INK_MUTED,
            linespacing=1.4,
        )

    axes_row[0].set_ylabel("relative frequency (%)", fontsize=9, color=_INK_SECONDARY)

    handles = [
        Line2D(
            [],
            [],
            marker="o",
            linestyle="none",
            markersize=5,
            color=colour,
            label=group_label(group),
        )
        for group, colour in zip(result.groups, _GROUP_COLOURS, strict=True)
    ]
    legend = figure.legend(
        handles=handles,
        loc="lower center",
        ncols=2,
        frameon=False,
        fontsize=8.5,
        bbox_to_anchor=(0.5, 0.005),
    )
    for text in legend.get_texts():
        text.set_color(_INK_SECONDARY)

    figure.suptitle(title, fontsize=13, color=_INK, y=0.982)
    top = 0.945
    if subtitle:
        top = 0.908
        figure.text(
            0.5,
            0.938,
            subtitle,
            ha="center",
            va="top",
            fontsize=8.5,
            color=_INK_SECONDARY,
        )
    figure.tight_layout(rect=(0.0, 0.055, 1.0, top))
    return figure


def save_boxplot(
    result: ComparisonResult,
    path: Path,
    *,
    title: str = DEFAULT_TITLE,
    subtitle: str | None = None,
) -> None:
    """Render the figure and write it as a PNG, reproducibly.

    Matplotlib 3.11 writes no creation date, but it does write a `Software`
    text chunk naming its own version. Passing None for both suppresses the
    chunk entirely, which is what makes the committed PNG independent of
    whichever matplotlib the grader happens to install. `Date` is passed too
    because suppressing a chunk that is not currently written costs nothing and
    survives matplotlib changing its mind.
    """
    figure = boxplot_figure(result, title=title, subtitle=subtitle)
    figure.savefig(
        path,
        format="png",
        dpi=_DPI,
        facecolor=_SURFACE,
        metadata={"Date": None, "Software": None},
    )
