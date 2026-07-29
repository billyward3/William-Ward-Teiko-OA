"""HTTP interface to the analysis, and the server that hosts the dashboard.

This is a translation layer, not a second implementation. Every number it
returns comes out of `summary_page`, `compare`, `subset_counts` or `mean_count`,
and nothing here recomputes any of them. The one query it owns is the list of
values each filter can take, which is a question about the database rather than
about the analysis.

Three decisions are worth stating, because each of them is a trap the shape of
the response does not reveal.

**An empty query parameter means unconstrained.** `Cohort` treats `None` as
unconstrained and `""` as a value to match, and no subject has an empty
condition, so passing a cleared dropdown straight through would return an empty
table with nothing to say why. The coercion belongs here rather than in
`Cohort`, where it would make an empty string silently unexpressible.

**Each endpoint's parameters default to the cohort its Part of the spec asks
about.** A bare `/api/comparison` answers Part 3, `/api/subsets` answers Part 4,
`/api/mean-count` answers the submission form, and `/api/summary` returns the
whole table because that is what Part 2 asks for. The defaults are imported from
`pipeline`, not restated, so the dashboard and the committed outputs cannot
disagree about what Part 3 means. That import costs an unused matplotlib in this
process, which is a fair price for the two never drifting apart.

It also keeps the landing state fast. `compare` materialises every pairwise
difference to invert the rank test, so the unfiltered cohort costs about five
seconds and 20 million differences per population. That cohort is still
reachable, by clearing the filters, but it is not what a dashboard opens on, and
it would be the wrong thing to open on even if it were free: it pools three
conditions, three treatments, two sample types, and three correlated samples per
subject.

**`UnknownSplitColumn` and `NotTwoGroups` are mapped separately.** Both subclass
`ComparisonError`, which subclasses `ValueError`, so a single `except ValueError`
would turn a divergence between this module's allowlist and `comparison.py`'s
into a tidy 400 that nobody would ever investigate. Only `NotTwoGroups` is
caught; the other is left to raise and be seen.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from cellcount.cohort import ALL_SAMPLES, FILTER_COLUMNS, Cohort
from cellcount.comparison import (
    ComparisonResult,
    NotTwoGroups,
    PopulationComparison,
    compare,
    simultaneous_alpha,
)
from cellcount.db import connect
from cellcount.filters import filter_options
from cellcount.loader import POPULATIONS
from cellcount.means import mean_count
from cellcount.pipeline import (
    BASELINE_COHORT,
    FORM_QUESTION_COHORT,
    FORM_QUESTION_POPULATION,
)
from cellcount.subsets import SubsetCounts, subset_counts
from cellcount.summary import SummaryPage, summary_page

HOST = "0.0.0.0"
"""Every interface, not loopback.

Grading happens in a GitHub Codespace, where a server bound to 127.0.0.1 is not
reliably reachable through the forwarded port.
"""

PORT = 8000
"""Declared in `.devcontainer/devcontainer.json` as well, and tested to match."""

API_PREFIX = "/api"

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000
"""Part 2 unfiltered is 52,500 rows and about 6.6 MB of JSON. The cap is what
makes paginating mean something."""

DATABASE_ENV_VAR = "CELLCOUNT_DB"
FRONTEND_ENV_VAR = "CELLCOUNT_FRONTEND_DIR"

DEFAULT_DATABASE = Path("cell-count.db")
DEFAULT_FRONTEND_DIR = Path("frontend/dist")

FRONTEND_MISSING_MESSAGE = (
    "The dashboard has not been built. Run `npm ci && npm run build` in "
    "frontend/, or use the API directly: /docs for the interactive reference, "
    "/api/filters for the available cohorts."
)

_BLANK_IS_UNCONSTRAINED = "Empty means unconstrained, so clearing it widens the cohort."

ConditionParam = Annotated[
    str | None, Query(description=f"Subject condition. {_BLANK_IS_UNCONSTRAINED}")
]
TreatmentParam = Annotated[
    str | None, Query(description=f"Treatment received. {_BLANK_IS_UNCONSTRAINED}")
]
ResponseParam = Annotated[
    str | None, Query(description=f"Response to treatment. {_BLANK_IS_UNCONSTRAINED}")
]
SexParam = Annotated[
    str | None, Query(description=f"Subject sex. {_BLANK_IS_UNCONSTRAINED}")
]
SampleTypeParam = Annotated[
    str | None, Query(description=f"Sample type. {_BLANK_IS_UNCONSTRAINED}")
]
TimepointParam = Annotated[
    list[str] | None,
    Query(
        description=(
            "Days from treatment start; repeat the parameter for several. "
            f"{_BLANK_IS_UNCONSTRAINED}"
        )
    ),
]


# --- request parsing --------------------------------------------------------


def _cleaned(value: str | None) -> str | None:
    """A filter value, or None if the client sent nothing usable.

    Whitespace is stripped and a blank result becomes None. No value in this
    dataset has leading or trailing space, so stripping cannot lose a real
    selection, and `?sex=%20` from a hand-built query string is far more likely
    to mean "no selection" than to mean a sex named " ".
    """
    if value is None:
        return None
    return value.strip() or None


def _parsed_timepoints(
    raw: list[str] | None, default: tuple[int, ...] | None
) -> tuple[int, ...] | None:
    """Timepoints from repeated query parameters, or the endpoint's default.

    Absent and blank are different: absent means the client said nothing and
    gets the default, blank means the client cleared the control and gets an
    unconstrained cohort. Without that distinction a defaulted endpoint would
    have a filter its user could not remove.
    """
    if raw is None:
        return default
    values: list[int] = []
    for item in raw:
        text = item.strip()
        if not text:
            continue
        try:
            values.append(int(text))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"timepoint must be a whole number of days, got {text!r}",
            ) from None
    return tuple(values) or None


def _cohort(
    condition: str | None,
    treatment: str | None,
    response: str | None,
    sex: str | None,
    sample_type: str | None,
    timepoint: list[str] | None,
    default_timepoints: tuple[int, ...] | None,
) -> Cohort:
    return Cohort(
        condition=_cleaned(condition),
        treatment=_cleaned(treatment),
        response=_cleaned(response),
        sex=_cleaned(sex),
        sample_type=_cleaned(sample_type),
        timepoints=_parsed_timepoints(timepoint, default_timepoints),
    )


def every_sample(
    condition: ConditionParam = ALL_SAMPLES.condition,
    treatment: TreatmentParam = ALL_SAMPLES.treatment,
    response: ResponseParam = ALL_SAMPLES.response,
    sex: SexParam = ALL_SAMPLES.sex,
    sample_type: SampleTypeParam = ALL_SAMPLES.sample_type,
    timepoint: TimepointParam = None,
) -> Cohort:
    """Part 2's cohort: every sample, unless the client narrows it."""
    return _cohort(
        condition,
        treatment,
        response,
        sex,
        sample_type,
        timepoint,
        ALL_SAMPLES.timepoints,
    )


def spec_cohort(
    condition: ConditionParam = BASELINE_COHORT.condition,
    treatment: TreatmentParam = BASELINE_COHORT.treatment,
    response: ResponseParam = BASELINE_COHORT.response,
    sex: SexParam = BASELINE_COHORT.sex,
    sample_type: SampleTypeParam = BASELINE_COHORT.sample_type,
    timepoint: TimepointParam = None,
) -> Cohort:
    """Parts 3 and 4's cohort: melanoma, miraclib, PBMC, baseline."""
    return _cohort(
        condition,
        treatment,
        response,
        sex,
        sample_type,
        timepoint,
        BASELINE_COHORT.timepoints,
    )


def form_question_cohort(
    condition: ConditionParam = FORM_QUESTION_COHORT.condition,
    treatment: TreatmentParam = FORM_QUESTION_COHORT.treatment,
    response: ResponseParam = FORM_QUESTION_COHORT.response,
    sex: SexParam = FORM_QUESTION_COHORT.sex,
    sample_type: SampleTypeParam = FORM_QUESTION_COHORT.sample_type,
    timepoint: TimepointParam = None,
) -> Cohort:
    """The submission form's cohort, which is deliberately wider than Part 4's."""
    return _cohort(
        condition,
        treatment,
        response,
        sex,
        sample_type,
        timepoint,
        FORM_QUESTION_COHORT.timepoints,
    )


def connection(request: Request) -> Iterator[sqlite3.Connection]:
    """One connection per request, closed when it ends.

    A sqlite3 connection belongs to the thread that opened it, and FastAPI runs
    these handlers in a worker pool, so it cannot be shared.

    A missing file is reported rather than created. `sqlite3.connect` would
    happily make an empty one, and every query after that would fail with a
    missing-table error that says nothing about the actual mistake.
    """
    database: Path = request.app.state.database
    if not database.is_file():
        raise HTTPException(
            status_code=503,
            detail=f"no database at {database}; run `make pipeline` first",
        )
    conn = connect(database)
    try:
        yield conn
    finally:
        conn.close()


Database = Annotated[sqlite3.Connection, Depends(connection)]
EverySample = Annotated[Cohort, Depends(every_sample)]
SpecCohort = Annotated[Cohort, Depends(spec_cohort)]
FormCohort = Annotated[Cohort, Depends(form_question_cohort)]


# --- response bodies --------------------------------------------------------


class CohortOut(BaseModel):
    """The cohort a response was computed over, echoed so a client can label it."""

    condition: str | None
    treatment: str | None
    response: str | None
    sex: str | None
    sample_type: str | None
    timepoints: list[int] | None

    @classmethod
    def of(cls, cohort: Cohort) -> CohortOut:
        return cls(
            condition=cohort.condition,
            treatment=cohort.treatment,
            response=cohort.response,
            sex=cohort.sex,
            sample_type=cohort.sample_type,
            timepoints=None if cohort.timepoints is None else list(cohort.timepoints),
        )


class FilterOptionsOut(BaseModel):
    """Everything a client needs to build its controls without guessing values."""

    fields: dict[str, list[str]]
    timepoints: list[int]
    populations: list[str]
    split_columns: list[str]
    default_cohort: CohortOut


class SummaryRowOut(BaseModel):
    """Part 2's columns, in the order the spec lists them."""

    sample: str
    total_count: int
    population: str
    count: int
    percentage: float


class SummaryOut(BaseModel):
    cohort: CohortOut
    rows: list[SummaryRowOut]
    total: int
    """Rows matching the cohort, before this page was cut out of them."""
    limit: int
    offset: int

    @classmethod
    def of(
        cls, cohort: Cohort, page: SummaryPage, *, limit: int, offset: int
    ) -> SummaryOut:
        return cls(
            cohort=CohortOut.of(cohort),
            rows=[
                SummaryRowOut(
                    sample=row.sample,
                    total_count=row.total_count,
                    population=row.population,
                    count=row.count,
                    percentage=row.percentage,
                )
                for row in page.rows
            ],
            total=page.total,
            limit=limit,
            offset=offset,
        )


class PopulationComparisonOut(BaseModel):
    population: str
    n: dict[str, int]
    median: dict[str, float]
    values: dict[str, list[float]]
    """Every observation, per group, so the client can draw the boxplot from the
    same numbers the statistics were computed from."""
    p_value: float | None
    q_value: float | None
    """Benjamini-Hochberg across the tested populations. This, not the interval,
    is what decides significance."""
    shift: float | None
    shift_ci: tuple[float, float] | None
    simultaneous_ci: tuple[float, float] | None
    effect_size: float | None

    @classmethod
    def of(cls, comparison: PopulationComparison) -> PopulationComparisonOut:
        return cls(
            population=comparison.population,
            n=comparison.n,
            median=comparison.median,
            values=comparison.values,
            p_value=comparison.p_value,
            q_value=comparison.q_value,
            shift=comparison.shift,
            shift_ci=comparison.shift_ci,
            simultaneous_ci=comparison.simultaneous_ci,
            effect_size=comparison.effect_size,
        )


class ComparisonOut(BaseModel):
    cohort: CohortOut
    split_on: str
    groups: list[str]
    n_samples: dict[str, int]
    n_subjects: dict[str, int]
    repeated_measures: bool
    """True when a subject contributed more than one sample, which means the
    observations are not independent and the test's p-value is optimistic."""
    n_tested: int
    alpha: float
    simultaneous_alpha: float
    """The level each `simultaneous_ci` was computed at, so a caption can say
    what the interval covers rather than implying it covers everything."""
    populations: list[PopulationComparisonOut]

    @classmethod
    def of(cls, result: ComparisonResult) -> ComparisonOut:
        return cls(
            cohort=CohortOut.of(result.cohort),
            split_on=result.split_on,
            groups=list(result.groups),
            n_samples=result.n_samples,
            n_subjects=result.n_subjects,
            repeated_measures=result.repeated_measures,
            n_tested=result.n_tested,
            alpha=result.alpha,
            simultaneous_alpha=simultaneous_alpha(result.alpha, result.n_tested),
            populations=[
                PopulationComparisonOut.of(comparison)
                for comparison in result.populations
            ],
        )


class SubsetsOut(BaseModel):
    cohort: CohortOut
    samples_per_project: dict[str, int]
    """Samples, as the spec words the question."""
    subjects_per_response: dict[str, int]
    """Distinct subjects, as the spec words this one. The grain differs by row."""
    subjects_per_sex: dict[str, int]

    @classmethod
    def of(cls, cohort: Cohort, counts: SubsetCounts) -> SubsetsOut:
        return cls(
            cohort=CohortOut.of(cohort),
            samples_per_project=counts.samples_per_project,
            subjects_per_response=counts.subjects_per_response,
            subjects_per_sex=counts.subjects_per_sex,
        )


class MeanCountOut(BaseModel):
    cohort: CohortOut
    population: str
    mean_count: float | None
    """Null when the cohort matched nothing. Zero would be a real mean."""


# --- endpoints --------------------------------------------------------------

router = APIRouter(prefix=API_PREFIX)


@router.get("/filters", summary="Values each cohort filter can take")
def read_filters(conn: Database) -> FilterOptionsOut:
    """What a client should offer, taken from the database.

    Filters are exact-match and case-sensitive, so `condition=Melanoma` is not a
    near miss: it is an empty result. Choosing from these removes that whole
    class of mistake, and `default_cohort` is where the dashboard should open.
    """
    options = filter_options(conn)
    return FilterOptionsOut(
        fields=options.fields,
        timepoints=options.timepoints,
        populations=options.populations,
        split_columns=sorted(FILTER_COLUMNS),
        default_cohort=CohortOut.of(BASELINE_COHORT),
    )


@router.get("/summary", summary="Part 2: relative frequency per sample")
def read_summary(
    conn: Database,
    cohort: EverySample,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SummaryOut:
    """One row per sample and population, paginated.

    The bounds on `limit` and `offset` are the schema's rather than the
    library's on purpose: `summary_page` raises `ValueError` for a negative one,
    which would surface as a 500 for what is plainly a bad request.
    """
    page = summary_page(conn, cohort, limit=limit, offset=offset)
    return SummaryOut.of(cohort, page, limit=limit, offset=offset)


@router.get("/comparison", summary="Part 3: responders against non-responders")
def read_comparison(
    conn: Database,
    cohort: SpecCohort,
    split_on: Annotated[
        str, Query(description="Cohort field to split the two groups on.")
    ] = "response",
    alpha: Annotated[float, Query(gt=0, lt=1)] = 0.05,
) -> ComparisonOut:
    """Mann-Whitney U per population, corrected across the populations tested.

    A cohort that yields one group is a 400: selecting `response=yes` and
    splitting on response is an ordinary thing to click, and it is the client's
    mistake, not the server's.

    `UnknownSplitColumn` is deliberately not caught. It can only mean the
    allowlist checked here and the one in `comparison.py` have diverged, which
    is a defect that should surface as a 500 rather than be filed under bad
    input.
    """
    if split_on not in FILTER_COLUMNS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"cannot split on {split_on!r}; "
                f"expected one of {sorted(FILTER_COLUMNS)}"
            ),
        )
    try:
        result = compare(conn, cohort, split_on, alpha)
    except NotTwoGroups as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ComparisonOut.of(result)


@router.get("/subsets", summary="Part 4: breakdowns of the filtered subset")
def read_subsets(conn: Database, cohort: SpecCohort) -> SubsetsOut:
    """Samples per project, and subjects per response and per sex.

    The counting units differ between the rows, which is how the spec words the
    questions. Categories the cohort matched none of are reported as zero.
    """
    return SubsetsOut.of(cohort, subset_counts(conn, cohort))


@router.get("/mean-count", summary="Mean absolute count for a population")
def read_mean_count(
    conn: Database,
    cohort: FormCohort,
    population: Annotated[
        str, Query(description="One of the populations from /api/filters.")
    ] = FORM_QUESTION_POPULATION,
) -> MeanCountOut:
    """An absolute count, not the relative frequency Part 2 reports.

    The population is checked here so an unknown one is a 400 naming the valid
    choices, rather than the 500 an unhandled `ValueError` would produce.
    """
    if population not in POPULATIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown population {population!r}; "
                f"expected one of {sorted(POPULATIONS)}"
            ),
        )
    return MeanCountOut(
        cohort=CohortOut.of(cohort),
        population=population,
        mean_count=mean_count(conn, cohort, population),
    )


# --- the application --------------------------------------------------------


def _path_from_env(variable: str, default: Path) -> Path:
    value = os.environ.get(variable)
    return Path(value) if value else default


def create_app(
    *, db_path: Path | None = None, frontend_dir: Path | None = None
) -> FastAPI:
    """Build the application, serving the built frontend if there is one.

    Paths are arguments first and environment variables second, so a test can
    point the app at a database in `tmp_path` without touching the process
    environment.

    The static mount is conditional. The frontend is built by a separate
    toolchain that may not have run, or may have failed, and an import-time
    crash would take the API down with it for no reason: the analysis endpoints
    do not depend on the dashboard existing.
    """
    database = db_path or _path_from_env(DATABASE_ENV_VAR, DEFAULT_DATABASE)
    frontend = frontend_dir or _path_from_env(FRONTEND_ENV_VAR, DEFAULT_FRONTEND_DIR)

    app = FastAPI(
        title="Loblaw Bio cell counts",
        description=(
            "Parts 2 to 4 of the analysis, recomputed per cohort. Every endpoint "
            "takes the same cohort filters; each defaults to the cohort its Part "
            "of the spec asks about."
        ),
        version="0.1.0",
    )
    app.state.database = database
    app.include_router(router)

    # Registered last, so /api and the OpenAPI routes are matched before it.
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="dashboard")
    else:

        @app.get("/", include_in_schema=False)
        def dashboard_not_built() -> dict[str, str]:
            return {"message": FRONTEND_MISSING_MESSAGE}

    return app


app = create_app()
"""The instance `uvicorn cellcount.api:app` and `make dashboard` serve."""


def main() -> None:
    """Start the server. This is what `make dashboard` runs."""
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
