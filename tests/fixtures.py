"""A synthetic cell-count CSV for the pipeline tests.

Shaped so that a wrong implementation cannot pass by accident. Specifically:

Group sizes differ (7 non-responders, 5 responders), so a statistic that uses
the other group's size is visible.

No two samples share a total, so a percentage computed against a global total,
or against another sample's, disagrees with one computed against the sample's
own.

Every count is off a round number, so no expected percentage is a whole number
and an integer division survives nowhere.

Each population's values are perturbed on a different modulus, so the five
populations get five *distinct* p-values. A writer that pairs a population with
the wrong population's statistics would otherwise be invisible.

Subjects contribute three samples each, so sample counts and subject counts
diverge wherever the spec distinguishes them.

The cohorts overlap only partially: one melanoma male responder is on
phauximab, and one is sampled as WB as well as PBMC. Both are excluded from
Part 3 and Part 4 but included in the form question, which is exactly the trap
the form question sets.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from cellcount.loader import POPULATIONS, REQUIRED_COLUMNS

Counts = tuple[int, int, int, int, int]

PBMC_TIMEPOINTS = (0, 7, 14)


def counts_for(seed: int) -> Counts:
    """Five counts that vary independently of one another.

    The linear term makes totals differ between samples; the modular term keeps
    the five populations from sharing a rank order, which is what gives the five
    populations distinct p-values.
    """
    return (
        40 + 3 * seed + (seed * 7) % 13,
        70 + 5 * seed + (seed * 11) % 17,
        110 + 7 * seed + (seed * 5) % 19,
        25 + 2 * seed + (seed * 3) % 11,
        200 + 11 * seed + (seed * 13) % 41,
    )


@dataclass(frozen=True)
class Sample:
    sample: str
    sample_type: str
    timepoint: int
    seed: int


@dataclass(frozen=True)
class Subject:
    subject: str
    project: str
    condition: str
    age: int
    sex: str
    treatment: str
    response: str
    seed: int
    extra: tuple[Sample, ...] = ()

    @property
    def samples(self) -> list[Sample]:
        pbmc = [
            Sample(
                sample=f"{self.subject}-pbmc-t{timepoint}",
                sample_type="PBMC",
                timepoint=timepoint,
                seed=4 * self.seed + index,
            )
            for index, timepoint in enumerate(PBMC_TIMEPOINTS)
        ]
        return pbmc + list(self.extra)


# Seeds interleave between the two response groups so the default fixture has
# no planted difference to find. `sbj10`'s seed is deliberately unused by any
# subject, which leaves 40..42 free for the extra WB sample below.
SUBJECTS: tuple[Subject, ...] = (
    Subject("sbj01", "prj1", "melanoma", 41, "M", "miraclib", "no", 2),
    Subject("sbj02", "prj1", "melanoma", 52, "M", "miraclib", "no", 5),
    Subject("sbj03", "prj1", "melanoma", 63, "F", "miraclib", "no", 9),
    Subject("sbj04", "prj1", "melanoma", 44, "M", "miraclib", "no", 12),
    Subject("sbj05", "prj3", "melanoma", 55, "F", "miraclib", "no", 16),
    Subject("sbj06", "prj3", "melanoma", 36, "M", "miraclib", "no", 19),
    Subject("sbj07", "prj3", "melanoma", 67, "M", "miraclib", "no", 23),
    Subject(
        "sbj08",
        "prj1",
        "melanoma",
        48,
        "M",
        "miraclib",
        "yes",
        1,
        extra=(Sample("sbj08-wb-t0", "WB", 0, 40),),
    ),
    Subject("sbj09", "prj1", "melanoma", 59, "F", "miraclib", "yes", 6),
    Subject("sbj10", "prj1", "melanoma", 33, "M", "miraclib", "yes", 11),
    Subject("sbj11", "prj3", "melanoma", 45, "F", "miraclib", "yes", 14),
    Subject("sbj12", "prj3", "melanoma", 71, "M", "miraclib", "yes", 21),
    # Melanoma, male, responder, but on the other drug: in the form question's
    # cohort and out of Part 3's and Part 4's.
    Subject("sbj13", "prj2", "melanoma", 50, "M", "phauximab", "yes", 31),
    Subject("sbj14", "prj2", "carcinoma", 62, "F", "phauximab", "no", 33),
    # Untreated control: no response to compare, so it must not reach Part 3.
    Subject("sbj15", "prj2", "healthy", 29, "F", "none", "", 36),
)

# The one project with no melanoma / miraclib / PBMC baseline sample, which is
# the case the real data also has and a plain GROUP BY silently omits.
PROJECTS = ("prj1", "prj2", "prj3")

B_CELL_SHIFT = 40
"""Counts added to `b_cell` for responders in the planted-difference variant.

Chosen so exactly one population clears the correction: large enough to
separate the two groups completely, small enough that the totals it drags with
it leave the other four populations null.
"""


def rows(*, b_cell_shift: int = 0) -> list[dict[str, str]]:
    """The fixture as CSV rows, optionally with a difference planted in b_cell.

    The shift is applied to responders only and is not absorbed elsewhere, so
    the sample totals move with it, exactly as a real difference in one
    population would.
    """
    out: list[dict[str, str]] = []
    for subject in SUBJECTS:
        for sample in subject.samples:
            counts = list(counts_for(sample.seed))
            if subject.response == "yes":
                counts[0] += b_cell_shift
            row = {
                "project": subject.project,
                "subject": subject.subject,
                "condition": subject.condition,
                "age": str(subject.age),
                "sex": subject.sex,
                "treatment": subject.treatment,
                "response": subject.response,
                "sample": sample.sample,
                "sample_type": sample.sample_type,
                "time_from_treatment_start": str(sample.timepoint),
            }
            row.update(
                dict(
                    zip(
                        POPULATIONS,
                        (str(count) for count in counts),
                        strict=True,
                    )
                )
            )
            out.append(row)
    return out


def write_csv(path: Path, *, b_cell_shift: int = 0) -> list[dict[str, str]]:
    """Write the fixture to `path` and return the rows written."""
    written = rows(b_cell_shift=b_cell_shift)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REQUIRED_COLUMNS))
        writer.writeheader()
        writer.writerows(written)
    return written
