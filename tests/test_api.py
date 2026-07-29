"""Tests for the HTTP layer.

The API is a translation, not a second implementation: every number it returns
comes from `summary_page`, `compare`, `subset_counts` or `mean_count`. What
these tests exercise is the translation itself, which is where the defects are.

Four things are worth naming, because none is visible to a test that only checks
status codes and key names.

**An empty query string is not a filter.** A cleared dropdown submits
`?response=`, and `Cohort(response="")` matches nothing rather than matching
everything. The two are indistinguishable in the shape of the response and
differ only in the numbers, so the assertions here are on the numbers.

**One-group and unknown-column failures are different failures.** Both raise
subclasses of `ComparisonError`, itself a `ValueError`, so a single
`except ValueError` would map a programmer error onto a 4xx and hide it. The
pair of tests below fails if they are ever collapsed.

**The parameter defaults are the spec's own cohorts**, one per endpoint, so a
bare request answers the Part it belongs to. A wrong default is only visible
against numbers derived from the fixture rather than from the API itself.

**The fixture is the pipeline's**, which has unequal groups (7 non-responders,
5 responders), no two samples sharing a total, three timepoints per subject, and
one melanoma male responder on the other drug who is inside the form question's
cohort and outside Part 3's and Part 4's.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

import fixtures
from cellcount import api
from cellcount.api import create_app
from cellcount.cohort import FILTER_COLUMNS
from cellcount.comparison import NotTwoGroups, UnknownSplitColumn
from cellcount.loader import POPULATIONS, build_database

SPEC_SUMMARY_COLUMNS = ["sample", "total_count", "population", "count", "percentage"]

SPEC_COHORT = {
    "condition": "melanoma",
    "treatment": "miraclib",
    "response": None,
    "sex": None,
    "sample_type": "PBMC",
    "timepoints": [0],
}
"""Parts 3 and 4's cohort, which is what the analysis endpoints default to."""

# Melanoma miraclib PBMC subjects in the fixture, by response.
BASELINE_NON_RESPONDERS = 7
BASELINE_RESPONDERS = 5


@pytest.fixture
def api_db(tmp_path: Path) -> Path:
    """An on-disk database built from the pipeline's synthetic CSV."""
    csv_path = tmp_path / "cell-count.csv"
    fixtures.write_csv(csv_path)
    db_path = tmp_path / "cell-count.db"
    build_database(csv_path, db_path)
    return db_path


@pytest.fixture
def client(api_db: Path) -> Iterator[TestClient]:
    with TestClient(create_app(db_path=api_db)) as test_client:
        yield test_client


def get(client: TestClient, path: str, **params: str | int | float) -> Any:
    """A successful GET, with the status asserted so a failure names the body."""
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


# --- filter options ---------------------------------------------------------


def test_filters_offer_every_cohort_field(client: TestClient) -> None:
    """Keyed by cohort field, so one entry becomes one control and one parameter."""
    body = get(client, "/api/filters")
    assert list(body["fields"]) == list(FILTER_COLUMNS)


def test_filters_come_from_the_data(client: TestClient) -> None:
    body = get(client, "/api/filters")
    assert body["fields"] == {
        "condition": ["carcinoma", "healthy", "melanoma"],
        "treatment": ["miraclib", "none", "phauximab"],
        "response": ["no", "yes"],
        "sex": ["F", "M"],
        "sample_type": ["PBMC", "WB"],
    }
    assert body["timepoints"] == [0, 7, 14]
    assert body["populations"] == sorted(POPULATIONS)


def test_filters_name_the_columns_a_comparison_can_split_on(
    client: TestClient,
) -> None:
    body = get(client, "/api/filters")
    assert body["split_columns"] == sorted(FILTER_COLUMNS)


def test_filters_carry_the_cohort_the_dashboard_should_open_on(
    client: TestClient,
) -> None:
    """So the dropdowns start where the statistics do, rather than blank."""
    body = get(client, "/api/filters")
    assert body["default_cohort"] == SPEC_COHORT


# --- Part 2: summary --------------------------------------------------------


def test_summary_rows_have_exactly_the_spec_columns(client: TestClient) -> None:
    body = get(client, "/api/summary")
    assert list(body["rows"][0]) == SPEC_SUMMARY_COLUMNS


def test_summary_defaults_to_every_sample(client: TestClient) -> None:
    """Part 2 is the whole table, so this endpoint's default is unconstrained."""
    body = get(client, "/api/summary")
    assert body["total"] == len(fixtures.rows()) * len(POPULATIONS)


def test_summary_pages_without_overlapping_or_skipping(client: TestClient) -> None:
    first = get(client, "/api/summary", limit=3, offset=0)
    second = get(client, "/api/summary", limit=3, offset=3)
    both = get(client, "/api/summary", limit=6, offset=0)

    assert len(first["rows"]) == 3
    assert first["rows"] + second["rows"] == both["rows"]
    assert first["total"] == second["total"] == both["total"]


def test_summary_echoes_the_page_it_served(client: TestClient) -> None:
    """A client that did not send limit still needs to know what it got."""
    body = get(client, "/api/summary", limit=4, offset=2)
    assert body["limit"] == 4
    assert body["offset"] == 2


def test_summary_last_page_is_short_rather_than_padded(client: TestClient) -> None:
    total = get(client, "/api/summary")["total"]
    body = get(client, "/api/summary", limit=10, offset=total - 3)
    assert len(body["rows"]) == 3


@pytest.mark.parametrize(
    ("parameter", "value"),
    [("limit", -1), ("offset", -1), ("limit", 0)],
)
def test_summary_rejects_an_unusable_page(
    client: TestClient, parameter: str, value: int
) -> None:
    """`summary_page` raises ValueError for these, which would otherwise be a 500."""
    response = client.get("/api/summary", params={parameter: value})
    assert response.status_code == 422, response.text


def test_summary_cohort_narrows_the_result(client: TestClient) -> None:
    everything = get(client, "/api/summary")["total"]
    responders = get(client, "/api/summary", response="yes")["total"]
    assert 0 < responders < everything


def test_summary_of_a_cohort_with_no_samples_is_empty_not_an_error(
    client: TestClient,
) -> None:
    """Both values exist; no subject has them together."""
    body = get(client, "/api/summary", condition="healthy", treatment="miraclib")
    assert body["rows"] == []
    assert body["total"] == 0


# --- the empty-string trap --------------------------------------------------


def test_a_cleared_filter_is_not_a_filter(client: TestClient) -> None:
    """`?response=` means the user cleared the dropdown, not `response = ""`.

    Passed through unchanged it builds `Cohort(response="")`, which matches no
    subject at all, so the difference shows up as a total of zero rather than as
    a malformed response.
    """
    everything = get(client, "/api/summary")["total"]
    cleared = get(client, "/api/summary", response="")["total"]
    assert cleared == everything


def test_a_cleared_filter_leaves_the_others_alone(client: TestClient) -> None:
    """A blank field must not widen or narrow the fields beside it."""
    melanoma = get(client, "/api/summary", condition="melanoma")["total"]
    with_blank = get(client, "/api/summary", condition="melanoma", response="")["total"]
    assert 0 < melanoma < get(client, "/api/summary")["total"]
    assert with_blank == melanoma


def test_whitespace_is_treated_as_cleared(client: TestClient) -> None:
    everything = get(client, "/api/summary")["total"]
    assert get(client, "/api/summary", sex="  ")["total"] == everything


def test_clearing_a_defaulted_filter_widens_the_cohort(client: TestClient) -> None:
    """On an endpoint whose parameters default to a cohort, blank must override.

    Otherwise the default is unclearable and the wider cohorts are unreachable.
    """
    body = get(client, "/api/comparison", condition="", treatment="", sample_type="")
    assert body["cohort"]["condition"] is None
    assert body["cohort"]["treatment"] is None
    assert body["cohort"]["sample_type"] is None


def test_a_cleared_timepoint_is_not_a_filter(client: TestClient) -> None:
    """The same rule for the multi-valued field, which is parsed by hand."""
    body = get(client, "/api/comparison", timepoint="")
    assert body["cohort"]["timepoints"] is None


def test_timepoints_accept_several_values(client: TestClient) -> None:
    response = client.get("/api/comparison?timepoint=0&timepoint=7")
    assert response.status_code == 200, response.text
    assert response.json()["cohort"]["timepoints"] == [0, 7]


def test_a_non_integer_timepoint_is_a_client_error(client: TestClient) -> None:
    response = client.get("/api/comparison", params={"timepoint": "baseline"})
    assert response.status_code == 400, response.text
    assert "baseline" in response.json()["detail"]


# --- Part 3: comparison -----------------------------------------------------


def test_comparison_defaults_to_the_spec_cohort(client: TestClient) -> None:
    """Part 3's cohort, which is also the cohort the dashboard opens on.

    The unfiltered comparison is both slower and less meaningful: it pools
    conditions, treatments, sample types, and three correlated samples per
    subject.
    """
    body = get(client, "/api/comparison")
    assert body["cohort"] == SPEC_COHORT
    assert body["groups"] == ["no", "yes"]
    assert body["n_samples"] == {
        "no": BASELINE_NON_RESPONDERS,
        "yes": BASELINE_RESPONDERS,
    }
    assert body["n_subjects"] == {
        "no": BASELINE_NON_RESPONDERS,
        "yes": BASELINE_RESPONDERS,
    }
    assert body["repeated_measures"] is False


def test_comparison_carries_what_a_boxplot_and_a_caption_need(
    client: TestClient,
) -> None:
    body = get(client, "/api/comparison")
    populations = body["populations"]
    assert [p["population"] for p in populations] == sorted(POPULATIONS)

    for population in populations:
        assert set(population["values"]) == {"no", "yes"}
        assert len(population["values"]["no"]) == BASELINE_NON_RESPONDERS
        assert len(population["values"]["yes"]) == BASELINE_RESPONDERS
        # Percentages, so the boxplot is not being handed raw counts.
        assert all(0.0 <= value <= 100.0 for value in population["values"]["no"])
        for field in ("p_value", "q_value", "shift", "effect_size"):
            assert isinstance(population[field], float), field
        for interval in ("shift_ci", "simultaneous_ci"):
            low, high = population[interval]
            assert low <= population["shift"] <= high

    assert body["n_tested"] == len(POPULATIONS)
    assert body["alpha"] == 0.05


def test_the_simultaneous_interval_is_the_wider_one(client: TestClient) -> None:
    """It has to be, or the joint claim it supports is not the one being made."""
    body = get(client, "/api/comparison")
    for population in body["populations"]:
        marginal_low, marginal_high = population["shift_ci"]
        joint_low, joint_high = population["simultaneous_ci"]
        assert joint_high - joint_low >= marginal_high - marginal_low
    assert body["simultaneous_alpha"] == pytest.approx(0.05 / len(POPULATIONS))


def test_comparison_reports_repeated_measures_when_timepoints_are_pooled(
    client: TestClient,
) -> None:
    """Each subject contributes three samples, so the flag has to flip."""
    body = get(client, "/api/comparison", timepoint="")
    assert body["repeated_measures"] is True
    assert body["n_samples"] == {
        "no": 3 * BASELINE_NON_RESPONDERS,
        "yes": 3 * BASELINE_RESPONDERS,
    }
    assert body["n_subjects"] == {
        "no": BASELINE_NON_RESPONDERS,
        "yes": BASELINE_RESPONDERS,
    }


def test_comparison_can_split_on_another_column(client: TestClient) -> None:
    body = get(client, "/api/comparison", split_on="sex")
    assert body["split_on"] == "sex"
    assert body["groups"] == ["F", "M"]


def test_comparison_of_an_empty_cohort_is_well_formed(client: TestClient) -> None:
    body = get(client, "/api/comparison", condition="healthy", treatment="miraclib")
    assert body["groups"] == []
    assert body["populations"] == []
    assert body["n_tested"] == 0


def test_one_group_is_the_users_mistake_not_the_servers(client: TestClient) -> None:
    """Selecting `response = yes` and splitting on response is a plausible click."""
    response = client.get("/api/comparison", params={"response": "yes"})
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "response" in detail
    assert "two groups" in detail


def test_an_unknown_split_column_is_rejected_before_it_reaches_the_analysis(
    client: TestClient,
) -> None:
    response = client.get("/api/comparison", params={"split_on": "astrology"})
    assert response.status_code == 400, response.text
    assert "astrology" in response.json()["detail"]


def test_an_unknown_split_column_reaching_the_analysis_is_a_server_error(
    api_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two `ComparisonError` subclasses must not be mapped together.

    `NotTwoGroups` is reachable by clicking. `UnknownSplitColumn` means this
    module's allowlist and `comparison.py`'s have diverged, which is a bug, and
    a single `except ValueError` would report it as a 4xx and hide it.
    """

    def raise_unknown(*args: object, **kwargs: object) -> None:
        raise UnknownSplitColumn("allowlists disagree")

    monkeypatch.setattr(api, "compare", raise_unknown)
    app = create_app(db_path=api_db)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/comparison")

    assert response.status_code == 500, response.text


def test_a_one_group_failure_is_still_a_client_error_when_raised_deeper(
    api_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the pair: the same handler must not swallow this one."""

    def raise_not_two(*args: object, **kwargs: object) -> None:
        raise NotTwoGroups("this cohort has 1 group")

    monkeypatch.setattr(api, "compare", raise_not_two)
    app = create_app(db_path=api_db)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/comparison")

    assert response.status_code == 400, response.text


@pytest.mark.parametrize("alpha", [0.0, 1.0, -0.1, 1.5])
def test_comparison_rejects_an_impossible_alpha(
    client: TestClient, alpha: float
) -> None:
    """`compare` raises ValueError for these, which would otherwise be a 500."""
    response = client.get("/api/comparison", params={"alpha": alpha})
    assert response.status_code == 422, response.text


def test_alpha_reaches_the_analysis(client: TestClient) -> None:
    """A wider alpha must produce narrower intervals, or it is being ignored."""
    wide = get(client, "/api/comparison", alpha=0.2)
    narrow = get(client, "/api/comparison", alpha=0.01)

    assert wide["alpha"] == 0.2
    assert wide["simultaneous_alpha"] == pytest.approx(0.2 / len(POPULATIONS))
    for at_wide, at_narrow in zip(
        wide["populations"], narrow["populations"], strict=True
    ):
        low_wide, high_wide = at_wide["shift_ci"]
        low_narrow, high_narrow = at_narrow["shift_ci"]
        assert high_wide - low_wide < high_narrow - low_narrow


# --- Part 4: subset counts --------------------------------------------------


def test_subsets_default_to_the_spec_cohort(client: TestClient) -> None:
    body = get(client, "/api/subsets")
    assert body["cohort"] == SPEC_COHORT
    assert body["subjects_per_response"] == {
        "no": BASELINE_NON_RESPONDERS,
        "yes": BASELINE_RESPONDERS,
    }
    assert body["subjects_per_sex"] == {"F": 4, "M": 8}


def test_subsets_report_a_project_with_no_matching_samples_as_zero(
    client: TestClient,
) -> None:
    """prj2 has no melanoma / miraclib / PBMC sample, and must not simply vanish."""
    body = get(client, "/api/subsets")
    assert body["samples_per_project"] == {"prj1": 7, "prj2": 0, "prj3": 5}


def test_subsets_count_samples_per_project_but_subjects_per_response(
    client: TestClient,
) -> None:
    """Pooling the timepoints triples the sample counts and leaves subjects alone."""
    body = get(client, "/api/subsets", timepoint="")
    assert body["samples_per_project"] == {"prj1": 21, "prj2": 0, "prj3": 15}
    assert body["subjects_per_response"] == {
        "no": BASELINE_NON_RESPONDERS,
        "yes": BASELINE_RESPONDERS,
    }


# --- the form question ------------------------------------------------------


def _form_question_rows() -> list[dict[str, str]]:
    """Melanoma males responding at baseline, across every treatment and type."""
    return [
        row
        for row in fixtures.rows()
        if row["condition"] == "melanoma"
        and row["sex"] == "M"
        and row["response"] == "yes"
        and row["time_from_treatment_start"] == "0"
    ]


def test_mean_count_defaults_to_the_form_questions_cohort(client: TestClient) -> None:
    """Wider than Part 4's: every treatment, every sample type, absolute counts.

    The expectation is derived from the fixture rows rather than from the API,
    so an endpoint that reused Part 4's cohort fails here rather than agreeing
    with itself.
    """
    expected_rows = _form_question_rows()
    # One phauximab subject and one WB sample, both outside Parts 3 and 4.
    assert len(expected_rows) == 5
    expected = sum(int(row["b_cell"]) for row in expected_rows) / len(expected_rows)

    body = get(client, "/api/mean-count")
    assert body["population"] == "b_cell"
    assert body["mean_count"] == pytest.approx(expected)
    assert body["cohort"] == {
        "condition": "melanoma",
        "treatment": None,
        "response": "yes",
        "sex": "M",
        "sample_type": None,
        "timepoints": [0],
    }


def test_mean_count_serves_another_population(client: TestClient) -> None:
    expected_rows = _form_question_rows()
    expected = sum(int(row["nk_cell"]) for row in expected_rows) / len(expected_rows)
    body = get(client, "/api/mean-count", population="nk_cell")
    assert body["mean_count"] == pytest.approx(expected)


def test_mean_count_of_an_empty_cohort_is_null_not_zero(client: TestClient) -> None:
    """Zero is a real mean. Absent is not, and a client must be able to tell."""
    body = get(client, "/api/mean-count", condition="healthy", treatment="miraclib")
    assert body["mean_count"] is None


def test_mean_count_rejects_an_unknown_population(client: TestClient) -> None:
    response = client.get("/api/mean-count", params={"population": "t_cell"})
    assert response.status_code == 400, response.text
    assert "t_cell" in response.json()["detail"]


# --- serving the frontend ---------------------------------------------------


def test_the_app_starts_without_a_built_frontend(api_db: Path, tmp_path: Path) -> None:
    """The frontend is built separately, and may not have been built at all."""
    app = create_app(db_path=api_db, frontend_dir=tmp_path / "not-built")
    with TestClient(app) as client:
        assert client.get("/api/filters").status_code == 200
        root = client.get("/")
        assert root.status_code == 200
        assert "npm" in root.json()["message"]


def test_a_built_frontend_is_served_at_the_root(api_db: Path, tmp_path: Path) -> None:
    """One process on one port, so a Codespace forwards one URL."""
    built = tmp_path / "dist"
    built.mkdir()
    (built / "index.html").write_text("<h1>dashboard</h1>", encoding="utf-8")

    app = create_app(db_path=api_db, frontend_dir=built)
    with TestClient(app) as client:
        assert client.get("/").text == "<h1>dashboard</h1>"
        # A mount at the root swallows everything registered after it, so the
        # API and its reference have to keep answering from behind one.
        assert client.get("/api/filters").status_code == 200
        assert client.get("/docs").status_code == 200
        assert client.get("/openapi.json").status_code == 200


# --- operational failures ---------------------------------------------------


def test_every_endpoint_answers_when_several_requests_arrive_at_once(
    api_db: Path,
) -> None:
    """The dashboard issues four requests on load, and they overlap.

    Each is handled on a worker thread, and a sync dependency's setup does not
    run on the same worker as the path operation that consumes it. A connection
    carrying sqlite3's default same-thread guard therefore fails as soon as two
    requests are in flight, while every sequential test above passes because the
    pool keeps handing back the one idle thread.

    This is the only test that puts more than one request in the air at a time,
    which is why it is the one that found it.
    """
    paths = [
        "/api/filters",
        "/api/summary",
        "/api/comparison",
        "/api/subsets",
        "/api/mean-count",
    ]
    app = create_app(db_path=api_db)
    # Server exceptions are turned into 500s rather than re-raised, so a failure
    # reports which endpoints broke instead of whichever traceback arrived first.
    with (
        TestClient(app, raise_server_exceptions=False) as client,
        ThreadPoolExecutor(max_workers=8) as pool,
    ):
        responses = list(pool.map(client.get, paths * 6))

    failed = {
        response.request.url.path
        for response in responses
        if response.status_code != 200
    }
    assert failed == set()


def test_a_missing_database_is_reported_rather_than_created(tmp_path: Path) -> None:
    """sqlite3 would create an empty file, and every query would then fail oddly."""
    missing = tmp_path / "cell-count.db"
    app = create_app(db_path=missing)
    with TestClient(app) as client:
        response = client.get("/api/summary")

    assert response.status_code == 503, response.text
    assert "make pipeline" in response.json()["detail"]
    assert not missing.exists()


def test_the_server_binds_all_interfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    """127.0.0.1 is not reliably reachable through Codespaces port forwarding."""
    recorded: dict[str, object] = {}

    def fake_run(app: object, **kwargs: object) -> None:
        recorded.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    api.main()
    assert recorded["host"] == "0.0.0.0"
    assert recorded["port"] == 8000


def test_the_forwarded_port_matches_the_devcontainer(repo_root: Path) -> None:
    """The port is declared in two places, and they have to agree."""
    devcontainer = json.loads(
        (repo_root / ".devcontainer" / "devcontainer.json").read_text(encoding="utf-8")
    )
    assert api.PORT in devcontainer["forwardPorts"]
