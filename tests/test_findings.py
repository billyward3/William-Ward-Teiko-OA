"""Tests for the generated Part 3 write-up.

The spec asks which populations differ significantly, with statistics good
enough to convince a colleague. On the delivered data the answer is "none", and
a null result is only worth reading if it is bounded: the document has to say
how large a difference the sample size can exclude, not merely that nothing
reached the threshold.

So the assertions here are about what the prose commits to. The results are
built by hand rather than by running `compare`, because the point is the
document's arithmetic and wording, and hand-built inputs make a wrong bound
distinguishable from a right one.
"""

from __future__ import annotations

from cellcount.cohort import Cohort
from cellcount.comparison import ComparisonResult, PopulationComparison
from cellcount.findings import findings_markdown

COHORT = Cohort(
    condition="melanoma", treatment="miraclib", sample_type="PBMC", timepoints=(0,)
)


def population(
    name: str,
    *,
    n: tuple[int, int] = (7, 5),
    medians: tuple[float, float] = (4.0, 4.5),
    p_value: float | None = 0.4,
    q_value: float | None = 0.8,
    shift: float | None = -0.5,
    ci: tuple[float, float] | None = (-1.25, 0.25),
    simultaneous: tuple[float, float] | None = None,
    effect_size: float | None = 0.42,
) -> PopulationComparison:
    """One population's statistics, with both interval levels set.

    `simultaneous` defaults to a widened `ci`, because a Bonferroni interval is
    always the wider of the two and a fixture that got that backwards would be
    describing something the code cannot produce. Cases that care about the
    difference set it explicitly.
    """
    if simultaneous is None and ci is not None:
        simultaneous = (ci[0] * 1.2, ci[1] * 1.2)
    return PopulationComparison(
        population=name,
        n={"no": n[0], "yes": n[1]},
        median={"no": medians[0], "yes": medians[1]},
        values={"no": [medians[0]] * n[0], "yes": [medians[1]] * n[1]},
        p_value=p_value,
        q_value=q_value,
        shift=shift,
        shift_ci=ci,
        simultaneous_ci=simultaneous,
        effect_size=effect_size,
    )


def result(
    populations: list[PopulationComparison],
    *,
    n_samples: tuple[int, int] = (7, 5),
    n_subjects: tuple[int, int] = (7, 5),
) -> ComparisonResult:
    return ComparisonResult(
        cohort=COHORT,
        split_on="response",
        groups=("no", "yes"),
        n_samples={"no": n_samples[0], "yes": n_samples[1]},
        n_subjects={"no": n_subjects[0], "yes": n_subjects[1]},
        repeated_measures=n_samples != n_subjects,
        n_tested=len([p for p in populations if p.p_value is not None]),
        alpha=0.05,
        populations=populations,
    )


# Shaped so that the two ways of collapsing an interval to a bound, and the two
# ways of ranking a shift, give different answers.
#
# `monocyte` is widest on its *upper* endpoint, so a half-width that read only
# the lower one would name `cd8_t_cell` and a smaller number. Every interval in
# an earlier version of this fixture was widest below zero, which let
# `max(abs(low), abs(high))` be replaced by `abs(low)` unnoticed; the real
# data's widest is `monocyte` at [-0.26, +1.10], an upper endpoint.
#
# `cd8_t_cell` carries the largest shift and it is negative, so a ranking that
# dropped the absolute value would name `monocyte` at +0.30. The delivered data
# has a positive largest shift at baseline and a negative one at both later
# timepoints, so only the signed version of this fixture catches it.
#
# The q-values are also deliberately distinct and ordered. An earlier version
# gave all five the same value, which let "the smallest q-value" be computed
# with `max` unnoticed. The delivered data has the same weakness: all five BH
# q-values are 0.885 and all five Benjamini-Yekutieli q-values are 1.000, so
# the real-data tests cannot distinguish the two either.
NULL_RESULT = result(
    [
        population(
            "b_cell",
            p_value=0.05,
            q_value=0.25,
            shift=-0.25,
            ci=(-0.80, 0.30),
            simultaneous=(-0.96, 0.42),
        ),
        population(
            "cd4_t_cell",
            p_value=0.12,
            q_value=0.30,
            shift=-0.10,
            ci=(-1.10, 0.90),
            simultaneous=(-1.34, 1.12),
        ),
        population(
            "cd8_t_cell",
            p_value=0.20,
            q_value=0.333,
            shift=-0.95,
            ci=(-1.60, 0.20),
            simultaneous=(-1.95, 0.35),
        ),
        population(
            "monocyte",
            p_value=0.30,
            q_value=0.375,
            shift=0.30,
            ci=(-0.25, 1.85),
            simultaneous=(-0.55, 2.40),
        ),
        population(
            "nk_cell",
            p_value=0.40,
            q_value=0.40,
            shift=-0.50,
            ci=(-0.60, 0.15),
            simultaneous=(-0.78, 0.28),
        ),
    ]
)


def test_reports_group_sizes_in_both_samples_and_subjects() -> None:
    """Pinned as a pair, so swapping the two counts fails rather than passes."""
    text = findings_markdown(
        result([population("b_cell")], n_samples=(12, 9), n_subjects=(6, 3))
    )
    assert "12 samples from 6 subjects" in text
    assert "9 samples from 3 subjects" in text


def test_says_observations_are_independent_when_they_are() -> None:
    assert "independent" in findings_markdown(NULL_RESULT).lower()


def test_flags_repeated_measures_when_a_subject_contributes_twice() -> None:
    text = findings_markdown(
        result([population("b_cell")], n_samples=(21, 15), n_subjects=(7, 5))
    ).lower()
    assert "repeated measures" in text


def test_explains_why_baseline_was_chosen() -> None:
    text = findings_markdown(NULL_RESULT).lower()
    assert "baseline" in text
    assert "time_from_treatment_start = 0" in text


def test_lists_every_population_with_its_statistics() -> None:
    text = findings_markdown(NULL_RESULT)
    for name in ("b_cell", "cd4_t_cell", "cd8_t_cell", "monocyte", "nk_cell"):
        assert name in text
    assert "0.333" in text  # cd8_t_cell's q-value, distinct from the rest
    assert "0.42" in text  # the effect size


def test_states_the_marginal_bound_as_the_widest_interval_half_width() -> None:
    """monocyte's interval reaches 1.85, on its upper endpoint."""
    text = findings_markdown(NULL_RESULT)
    assert "1.85 percentage points, in `monocyte`" in text
    assert "95%" in text
    assert "no population differs significantly" in text.lower()


def test_the_headline_bound_is_the_simultaneous_one() -> None:
    """The headline quantifies over populations, so it needs the joint level.

    Five marginal 95% intervals are a 75% statement about all five together.
    The marginal widest is 1.85; the Bonferroni-widened one is 2.40, and it is
    the second that the headline's "any shift larger than" is entitled to.
    """
    text = findings_markdown(NULL_RESULT)
    headline = text.split("## Cohort")[0]
    assert "2.40 percentage points" in headline
    assert "simultaneous" in headline
    assert "1.85" not in headline


def test_the_document_says_which_level_each_bound_carries() -> None:
    text = findings_markdown(NULL_RESULT)
    assert "marginal" in text
    assert "99%" in text  # alpha / 5, the per-interval level
    assert "75%" in text  # what five marginal 95% intervals guarantee jointly


def test_the_marginal_bound_moves_with_the_data() -> None:
    """A hardcoded bound would survive the previous tests but not this one."""
    wider = result(
        [
            population("b_cell", ci=(-0.80, 0.30)),
            population("cd4_t_cell", ci=(-3.40, 0.90)),
        ]
    )
    assert "3.40" in findings_markdown(wider)


def test_the_simultaneous_bound_moves_with_the_data() -> None:
    wider = result(
        [
            population("b_cell", ci=(-0.80, 0.30), simultaneous=(-0.96, 0.42)),
            population("cd4_t_cell", ci=(-1.10, 0.90), simultaneous=(-4.70, 1.12)),
        ]
    )
    assert "4.70" in findings_markdown(wider)


def test_names_the_population_carrying_the_largest_shift() -> None:
    """Ranked on magnitude: cd8_t_cell's -0.95 beats monocyte's +0.30."""
    text = findings_markdown(NULL_RESULT)
    assert "`cd8_t_cell` carries the largest estimated shift, -0.95" in text


def test_does_not_call_an_estimated_shift_an_observed_one() -> None:
    """The shift is a Hodges-Lehmann estimate; no sample holds that value."""
    assert "shift actually observed" not in findings_markdown(NULL_RESULT)


def test_names_the_significant_populations_when_there_are_any() -> None:
    """The document is generated, so it must not hardcode the null conclusion."""
    text = findings_markdown(
        result(
            [
                population("b_cell", p_value=0.001, q_value=0.005, shift=2.4),
                population("cd4_t_cell"),
            ]
        )
    )
    assert "b_cell" in text
    assert "no population differs significantly" not in text.lower()


def test_reports_an_untested_population_rather_than_dropping_it() -> None:
    text = findings_markdown(
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
    assert "monocyte" in text
    assert "not tested" in text.lower()


def test_flags_an_interval_that_excludes_zero_without_a_significant_q() -> None:
    """The two disagree by design, and a reader who reads only the interval
    would report a difference the correction does not support."""
    text = findings_markdown(
        result(
            [
                population("b_cell", ci=(0.20, 1.40), q_value=0.40),
                population("cd4_t_cell"),
            ]
        )
    )
    assert "b_cell" in text
    assert "excludes zero" in text.lower()


def test_says_nothing_about_disagreement_when_there_is_none() -> None:
    assert "excludes zero" not in findings_markdown(NULL_RESULT).lower()


def test_flags_the_same_disagreement_in_the_timepoint_panel() -> None:
    at_seven = result(
        [population("cd4_t_cell", ci=(-1.69, -0.08), q_value=0.15)],
    )
    text = findings_markdown(
        NULL_RESULT, by_timepoint=[(0, NULL_RESULT), (7, at_seven)]
    )
    assert "excludes zero" in text.lower()
    assert "t = 7" in text


def test_reports_the_per_timepoint_panel() -> None:
    text = findings_markdown(
        NULL_RESULT,
        by_timepoint=[(0, NULL_RESULT), (7, NULL_RESULT), (14, NULL_RESULT)],
    )
    assert "t = 14" in text
    assert "timepoint" in text.lower()


def test_the_timepoint_table_states_the_unit_of_its_group_sizes() -> None:
    """Everything else in this document counts subjects where it can, so an
    unlabelled pair of counts reads as subjects and these are samples."""
    text = findings_markdown(NULL_RESULT, by_timepoint=[(0, NULL_RESULT)])
    assert "| non-responder (samples) | responder (samples) |" in text


def test_the_timepoint_row_carries_the_values_its_header_promises() -> None:
    """Pinned as a whole row: samples, samples, family size, smallest q, and a
    bound that is the marginal 1.85 rather than the simultaneous 2.40."""
    text = findings_markdown(NULL_RESULT, by_timepoint=[(0, NULL_RESULT)])
    assert "| t = 0 | 7 | 5 | 5 | 0.250 | 1.85 |" in text


def test_says_correction_is_applied_within_each_timepoint() -> None:
    text = findings_markdown(
        NULL_RESULT, by_timepoint=[(0, NULL_RESULT), (7, NULL_RESULT)]
    ).lower()
    assert "within each timepoint" in text


def test_mentions_a_timepoint_that_could_not_be_compared() -> None:
    text = findings_markdown(
        NULL_RESULT, by_timepoint=[(0, NULL_RESULT)], skipped_timepoints=(7, 14)
    )
    assert "7 and 14" in text


def test_an_empty_result_is_reported_rather_than_crashing() -> None:
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
    assert "no samples" in findings_markdown(empty).lower()


def test_names_the_test_and_the_correction() -> None:
    text = findings_markdown(NULL_RESULT)
    assert "Mann-Whitney" in text
    assert "Benjamini-Hochberg" in text


def test_records_the_compositional_caveat() -> None:
    """Five frequencies that sum to 100 are not five independent measurements."""
    assert "sum to 100" in findings_markdown(NULL_RESULT).lower()


def test_says_the_positive_dependence_condition_is_not_established() -> None:
    """The claim must be exactly what closure forces, and no more.

    Two earlier versions of this paragraph were wrong in opposite directions.
    The first asserted positive dependence and used it to wave the
    Benjamini-Hochberg guarantee through. The second asserted that closure
    makes the parts negatively correlated, which is also false: closure forces
    each part's covariances with the rest to sum to minus its own variance, so
    the parts cannot all be positively related, but individual pairs may be. A
    five-part composition with six positive pairwise correlations is easy to
    construct.

    What survives both is the conclusion that actually matters, and it is the
    reason the document re-runs the correction under Benjamini-Yekutieli.
    """
    text = findings_markdown(NULL_RESULT).lower()
    assert "cannot all be positively related" in text
    assert "not something this design establishes" in text
    # The second overclaim must appear only in the sentence that denies it.
    assert "does not make every pair negatively correlated" in text


def test_re_runs_the_correction_under_benjamini_yekutieli() -> None:
    """Since the assumption cannot be asserted, the document checks instead.

    Every fixture p-value is 0.4, and Benjamini-Yekutieli multiplies by
    sum(1/i) over five terms, 2.2833, so the smallest q-value becomes 0.913.
    """
    text = findings_markdown(NULL_RESULT)
    assert "Benjamini-Yekutieli" in text
    assert "arbitrary dependence" in text
    # BH 0.250 -> BY 0.571. Both are quoted, so a swap or a dropped
    # harmonic factor changes the sentence.
    assert "0.250 to 0.571" in text


def test_the_yekutieli_verdict_follows_the_data() -> None:
    """A check whose answer is fixed in advance is not a check.

    Benjamini-Yekutieli is strictly more conservative, so a q-value near alpha
    can clear Benjamini-Hochberg and fail it. Here b_cell does.
    """
    borderline = result(
        [
            population("b_cell", p_value=0.02, q_value=0.04),
            population("cd4_t_cell", p_value=0.9, q_value=0.9),
        ]
    )
    text = findings_markdown(borderline)
    assert "`b_cell` clears alpha" in text
    assert "does rest on the dependence assumption" in text


def test_says_when_a_finding_survives_both_corrections() -> None:
    strong = result(
        [
            population("b_cell", p_value=0.0001, q_value=0.0002, shift=2.4),
            population("cd4_t_cell", p_value=0.9, q_value=0.9),
        ]
    )
    assert "clears it under Benjamini-Yekutieli too" in findings_markdown(strong)


def test_the_yekutieli_check_covers_the_timepoint_panel_too() -> None:
    """The document draws a conclusion per timepoint, so the check has to reach
    those families as well, not only the headline."""
    at_seven = result([population("b_cell", p_value=0.01, q_value=0.05)])
    text = findings_markdown(
        NULL_RESULT, by_timepoint=[(0, NULL_RESULT), (7, at_seven)]
    )
    assert "per-timepoint families" in text
    assert "t = 7" in text


def test_reports_how_many_populations_entered_the_correction() -> None:
    """A q-value without the size of the family it was corrected over is noise."""
    text = findings_markdown(NULL_RESULT)
    assert "5 populations" in text
