# Loblaw Bio cell counts

Immune cell population analysis for the miraclib trial: a SQLite schema and loader, the Part 2 to Part 4 analyses, a generated write-up of the Part 3 result, and an interactive dashboard.

`cell-count.csv` holds 10,500 samples from 3,500 subjects across 3 projects, five populations each, so 52,500 measurements in all.
Every subject contributes exactly three samples, at days 0, 7 and 14.

The Part 3 answer is a null result, and it is stated as a bounded one in [`outputs/findings.md`](outputs/findings.md).

---

## Running it

Three commands, in order.
The spec's three graded Make targets are the whole interface.

```sh
make setup      # install the Python package, build the dashboard front end
make pipeline   # load the CSV, write every output into outputs/
make dashboard  # serve the dashboard on port 8000
```

### In GitHub Codespaces

Open the repository in a Codespace and run the three commands above in the terminal.
`.devcontainer/devcontainer.json` pins Python 3.12 and Node 22, which is what CI builds against, so no other setup is needed.

`make setup` installs the package with `pip install -e ".[dev]"` into the container's Python, then builds the front end with `npm ci && npm run build`.
The front-end build is deliberately allowed to fail: its exit status is swallowed and reported as a warning, so a broken `npm` cannot take Parts 1 to 4 with it.
If that happens, `make pipeline` and every graded output still work, and `make dashboard` serves the API alone.

`make pipeline` rebuilds `cell-count.db` from `cell-count.csv` and writes seven artifacts into `outputs/`.
It takes about 3 seconds on a laptop and needs no arguments and no manual steps.

Part 1 also requires the loader to run standalone, and it does:

```sh
python load_data.py
```

That creates `cell-count.db` in the repository root with no arguments and no module-style invocation.
It calls the same `build_database` function `make pipeline` calls, so the two entry points cannot build different databases.

### Locally

Same three commands, with a virtualenv first.

```sh
python3.12 -m venv .venv && source .venv/bin/activate
make setup && make pipeline && make dashboard
```

---

## The dashboard

Nothing is deployed publicly, so the link is the one your own run creates.
The dashboard is served by this repository, on port 8000.

**In a Codespace:**

1. Run `make setup`, then `make pipeline`, then `make dashboard`.
2. Codespaces detects the port and offers to open it. The **Ports** panel lists port 8000, labelled `dashboard`.
3. The URL is `https://<your-codespace-name>-8000.app.github.dev`.

`.devcontainer/devcontainer.json` declares `forwardPorts: [8000]`, and the server binds `0.0.0.0` rather than loopback, because a Codespace forwards the port from outside the container.
The front end fetches `/api/...` on whatever origin served it and names no host anywhere, so the same bundle works locally and behind the forwarded HTTPS origin without a CORS or mixed-content exception.

**Locally:** the same command serves <http://127.0.0.1:8000>.

The dashboard opens on the spec's Part 3 and Part 4 cohort (melanoma, miraclib, PBMC, baseline).
Changing any filter re-runs the analysis on the server against the new cohort.
Nothing on the page is a stored result, and the page recomputes nothing client-side.
The API is under `/api`, with an interactive reference at `/docs`.

`make dashboard` needs the database, so run `make pipeline` first.
If you do not, the endpoints return a 503 saying so rather than a missing-table error.

---

## What the pipeline writes

| File | Part | Contents |
|---|---|---|
| `outputs/part2_summary.csv` | 2 | 52,500 rows: `sample`, `total_count`, `population`, `count`, `percentage` |
| `outputs/part3_comparison_baseline.csv` | 3 | Per population: group sizes, medians, shift, both intervals, p, q, effect size |
| `outputs/part3_boxplot_baseline.png` | 3 | One panel per population, every observation drawn, group sizes labelled |
| `outputs/part3_comparison_by_timepoint.csv` | 3 | The same comparison at t = 0, 7 and 14, each corrected within itself |
| `outputs/findings.md` | 3 | The write-up: cohort, method, results, and what the sample size rules out |
| `outputs/part4_subsets.csv` | 4 | Samples per project, subjects per response, subjects per sex |
| `outputs/form_answer.md` | form | The submission form's mean B cell count, and the cohort it was taken over |

### The Part 3 result

No population differs significantly between responders and non-responders at baseline.
All five q-values are 0.885.

That is a finding rather than a gap, and [`outputs/findings.md`](outputs/findings.md) states it as a bounded negative: at 95% simultaneous confidence over all five populations, the data rule out any shift larger than 1.32 percentage points.
For scale, the widest bound belongs to `monocyte`, which sits at roughly 20% of a sample, so the study can exclude a large relative difference and not a small one.
The document also reports what the bound rests on, why baseline was used, and a re-run of the correction under Benjamini-Yekutieli as a check on the dependence assumption.

---

## Database schema

Five tables and one view, in a star.
`cell_counts` is the fact table; `projects`, `subjects`, `samples` and `populations` are dimensions.

```
projects(project_id)
    |
subjects(subject_id, project_id, condition, age, sex, treatment, response)
    |
samples(sample_id, subject_id, sample_type, time_from_treatment_start)
    |                                       UNIQUE(subject_id, sample_type, time_from_treatment_start)
cell_counts(sample_id, population_id, count)
    |                  PRIMARY KEY(sample_id, population_id)
populations(population_id, name)

sample_frequencies   view: each count as a percentage of its own sample's total
```

The DDL is in [`src/cellcount/db.py`](src/cellcount/db.py).

### Why this shape

**Counts are stored long, one row per sample and population, rather than as five columns on `samples`.**
A sixth population is then an `INSERT` into `populations` instead of a schema migration, and Part 2's required output shape falls out of storage rather than needing an unpivot.
This is the decision the rest of the schema's flexibility rests on.

**Attributes constant within a subject live on `subjects`.**
`project`, `condition`, `age`, `sex`, `treatment` and `response` do not vary across a subject's three samples in the delivered file.
That is checked rather than assumed: `tests/test_data_characteristics.py` asserts it against `cell-count.csv`, and the loader re-checks it on every run and raises `DataValidationError` naming the subject and column if it ever fails.
Storing them once means a subject-level question counts subjects and a sample-level question counts samples, with no risk of double-counting a subject three times because their attributes were repeated on every row.

**`samples` carries a natural key alongside its surrogate id.**
`UNIQUE (subject_id, sample_type, time_from_treatment_start)` says a subject cannot have two samples of the same type at the same timepoint.
The database enforces the thing that is actually true, rather than trusting whatever generated the `sample` ids.

**`sample_frequencies` is a view, not a materialized table.**
The percentage arithmetic is defined once and cannot drift from the counts it derives from, so Part 3 genuinely reads "the data reported in the summary table" the way the spec words it.

**Foreign keys are enforced.**
SQLite disables them by default, per connection rather than per database, so every caller has to opt in.
`db.connect()` is the only place a connection is opened, and it issues `PRAGMA foreign_keys = ON`, which means no code path can silently skip it.

**Indexes cover the foreign keys and the filter columns**: `subjects(project_id)`, `subjects(condition, treatment, response, sex)`, `samples(subject_id)`, `samples(sample_type, time_from_treatment_start)` and `cell_counts(population_id)`.
`EXPLAIN QUERY PLAN` on the Part 3 query confirms they are used: the composite index on `subjects` serves the cohort filter, and the natural key on `samples` serves the join.

### How it scales

Three different questions get blurred together under the word "scale", so they are answered separately.

#### Volume

Hundreds of projects and thousands of samples is not a large database, and it is worth saying so plainly.

The delivered data is 3 projects, 3,500 subjects, 10,500 samples and 52,500 rows in `cell_counts`, in a 4.4 MB file.
Grow that to 500 projects and 50,000 samples at this panel size and the fact table holds 250,000 rows, roughly 20 MB by linear extrapolation.
SQLite is comfortable there and stays comfortable to somewhere around 10<sup>7</sup> rows on ordinary hardware.

The work required is indexes on the foreign keys and on the columns cohorts filter on, which the schema already has, and nothing more dramatic.
Current measurements, on the full dataset on a laptop: the whole Part 3 comparison for the melanoma / miraclib / PBMC / baseline cohort takes 0.04 s, and the unfiltered Part 2 table, all 52,500 rows, takes 0.15 s.
At five times the data those are still interactive.
Adding a warehouse, a cache or a materialized rollup at this size would cost more than it returns, and performing complexity here would be worse than not.

#### Schema evolution

Three kinds of change are likely, and the long fact table absorbs most of them as inserts rather than migrations.

*Larger panels.*
A 30-marker panel is 25 `INSERT`s into `populations`.
The fact table grows by rows; no table grows a column, and no existing query changes.
The five-column alternative would need a migration per marker and would leave every older sample with 25 null columns.

*Batch, instrument and acquisition metadata.*
These are sample-level attributes, so they are columns on `samples`, or a `batches` dimension keyed from `samples` once batch attributes repeat across samples.
Either way the fact table is untouched, and a cohort filter on batch is one more entry in the filter vocabulary described below.

*Other assay types.*
The fact table's grain is (sample, thing measured, value), which generalizes.
A second assay that also produces a count per population per sample is an `assays` dimension plus one more column in the fact table's key.
A second assay whose value means something different, say a fluorescence intensity rather than a count, should get its own fact table at its own grain, because storing two incomparable units in one `count` column would make every aggregate over it wrong in a way no constraint could catch.

#### Analytical variety

This is where the subject/sample split earns its place.
Because subject-level attributes are stored once and the sample grain is separate, a question about subjects and a question about samples are the same query with a different count.
Part 4 already does exactly that: samples per project, distinct subjects per response and per sex, from one table with one filter.

New questions are therefore new `GROUP BY` clauses rather than new code.
Per-project response rates, per-timepoint trajectories, sex-stratified comparisons and per-condition breakdowns are all the same shape as what is here.

The filter vocabulary is single-sourced to keep that true above the SQL as well.
`Cohort` is one frozen dataclass with three representations: arguments to the analysis functions, a bound `WHERE` clause, and query parameters over HTTP.
Adding a filter column means one entry in `FILTER_COLUMNS`, and it becomes available to every analysis function, to the API, to the comparison's `split_on`, and to the dashboard's dropdowns at once.

#### Where it breaks, and what to do then

Two limits are real rather than hypothetical.

Past roughly 10<sup>7</sup> fact rows, index maintenance and any query that scans the fact table start to dominate, and a single-file embedded database is the wrong host.
And SQLite takes one writer at a time: a nightly ingestion job is fine, several instruments streaming results in concurrently is not.

The move at that point is Postgres, with `cell_counts` partitioned by project, which matches both how the data arrives and how it is removed when a study ends.
If the workload stays read-mostly and analytical, DuckDB is the better answer, since columnar storage over a long fact table is a large win for exactly the aggregate-and-group-by queries this schema is built for.

Either is a change of host, not a change of design.
The star schema, the long counts, the subject/sample split and the dimension tables all carry over unchanged, and the SQL in this repository is ordinary enough to move mostly as it stands.

---

## Code structure

```
load_data.py              Part 1's standalone entry point, at the root as the spec requires
Makefile                  the three graded targets, plus supporting and development ones
cell-count.csv            the delivered input
src/cellcount/
  db.py                   schema DDL, and the only place a connection is opened
  loader.py               CSV validation and load
  cohort.py               the filter vocabulary
  filters.py              the values each filter can take, read from the data
  summary.py              Part 2: relative frequencies
  comparison.py           Part 3: Mann-Whitney U, correction, effect sizes, intervals
  subsets.py              Part 4: breakdowns, in two counting units
  means.py                absolute means, for the form question
  plots.py                the Part 3 figure
  findings.py             the Part 3 write-up, generated from the result
  pipeline.py             `make pipeline`: one run, every artifact
  api.py                  `make dashboard`: HTTP interface and static hosting
frontend/                 React and TypeScript dashboard
tests/                    297 tests
outputs/                  committed, and regenerated byte for byte by `make pipeline`
```

Three ideas hold it together.

**One analysis library, two consumers.**
`pipeline.py` writes files and `api.py` answers HTTP requests, and both call the same four functions: `summary_page`, `compare`, `subset_counts` and `mean_count`.
Neither recomputes anything.
`api.py` imports the spec's cohort definitions from `pipeline.py` rather than restating them, so the dashboard and the committed outputs cannot disagree about what Part 3 means.

**`Cohort` is the single filter vocabulary.**
One frozen dataclass, one function that renders it to a bound `WHERE` clause, and one HTTP layer that parses it from query parameters.
`None` means unconstrained, so Part 3's tight cohort and the form question's much looser one are both expressible without special cases, and the difference between them is visible at the call site.

**SQL owns retrieval and aggregation; Python owns statistics and rendering.**
The dashboard recomputes for arbitrary cohorts, so filtering has to happen in the database rather than in Python over a table loaded into memory.
Every value reaching SQL is a bound parameter.
The only strings interpolated into SQL are column names, each drawn from a fixed allowlist, because a column name cannot be a bound parameter.

Two smaller conventions worth knowing.
Library functions take paths as arguments and never derive their own location, which is what lets tests hand them synthetic inputs; `load_data.py` at the root is the single place that resolves real filesystem paths.
And `findings.md` is generated from the `ComparisonResult` rather than written by hand, so it cannot go on saying "nothing is significant" after the data changes.

---

## Assumptions

Each of these is a real decision made while building, not a hypothetical.

**Column names come from the CSV, not from the spec's prose.**
The spec's metadata list and the actual header disagree.

| Spec prose | CSV header |
|---|---|
| `sample_id` | `sample` |
| `indication` | `condition` |
| `gender` | `sex` |

The CSV is treated as authoritative, which is also what the spec itself does: Part 2 specifies an output column named `sample`, matching the file rather than its own prose.
The header also carries `project`, `subject`, `age` and `sample_type`, which the prose never mentions but Parts 3 and 4 depend on.

**Part 4 counts samples for one question and subjects for the other two.**
The spec asks how many *samples* come from each project, but how many *subjects* were responders and how many were male or female.
Both counting units are enforced in SQL, and `outputs/part4_subsets.csv` carries a `unit` column saying which each row used.

The care is invisible in this dataset, which is the reason to explain it.
Every subject in the delivered file has exactly one sample at t = 0, and all three of a subject's samples share one type, so inside this cohort each subject contributes exactly one sample.
Both units therefore come to 656, and the results (384 + 0 + 272 samples; 325 + 331 subjects; 312 + 344 subjects) would be identical either way.
They stop being identical the moment a subset spans more than one timepoint, or a future subject gives both a PBMC and a WB sample on the same day.
A query that had quietly been using the wrong unit would start returning wrong numbers with nothing in the code having changed.

`prj2` has no matching samples at all and is reported as `0` rather than omitted.
A plain `GROUP BY` drops it, which reads as though the project does not exist.

**Part 3 uses baseline samples only.**
Each subject contributes three samples, at t = 0, 7 and 14.
Mann-Whitney assumes independent observations, and pooling the timepoints would count several correlated samples from one subject as several independent ones.
A rank test fed pseudo-replicates returns p-values that are too small.
Restricting to baseline costs almost no power: the arms still hold 325 and 331 subjects.

Baseline also answers the question that was asked.
A difference measured before treatment could be used to choose treatment; a difference that appears afterwards may be a consequence of responding rather than a predictor of it.
The per-timepoint panel is still emitted, in `outputs/part3_comparison_by_timepoint.csv`, as a consistency check rather than as three separate studies.

`ComparisonResult` reports `n_samples`, `n_subjects` and a `repeated_measures` flag, so a cohort that does pool timepoints says so in the return type, in the figure, and on the dashboard rather than looking like a larger study than it is.

**The five frequencies sum to 100, so they are not five independent measurements.**
A shift in one implies compensating shifts in the others.
Closure forces each part's covariances with the other four to sum to minus its own variance, so the parts cannot all be positively related to one another.

That is not the same as every pair being negatively correlated, and neither statement is what the correction needs.
What it means practically is that the positive regression dependence Benjamini-Hochberg is proved under is not something this design establishes.
So the same p-values are re-corrected under Benjamini-Yekutieli, which holds under arbitrary dependence, as a check rather than a replacement.
Nothing reaches alpha under either correction, so the conclusion does not rest on the assumption.

**Blank `response` means "not applicable", not "unknown" and not a third group.**
The 474 healthy subjects, who are also the untreated ones, have no response value across all 1,422 of their samples.
They are loaded as NULL and excluded from a response split, rather than being treated as a group to compare against.

**Relative frequency and absolute count are kept distinct.**
Parts 2 and 3 are about relative frequencies.
The submission form asks for a mean absolute B cell count over a deliberately looser cohort: melanoma males across all sample types and all treatments.
Reusing Part 4's filter there produces a different, confidently wrong number, so it goes through `means.py` against its own cohort, recorded in `outputs/form_answer.md` along with the filter it used.

**A sample's percentages are taken over the populations present for that sample.**
The loader guarantees all five are present and rejects a sample whose populations are all zero, since relative frequency would be undefined.
The schema does not enforce that on its own, so the view also guards the division defensively.

---

## What is committed, and what is generated

`outputs/` is committed, so the results can be read without running anything.
Regenerating it is a no-op: `make pipeline` is reproducible byte for byte, and CI fails if a re-run changes a single file.
That took CSVs written with LF endings whatever the platform, floats at a fixed precision, a fixed seed for the figure's jitter, and suppressing the PNG text chunk that would otherwise record which matplotlib drew it.

`cell-count.db` is **not** committed.
It is a 4.4 MB binary that `make pipeline` regenerates from the CSV in about 3 seconds, and the CSV is the source of truth.
`frontend/dist`, `node_modules` and the virtualenv are not committed either; `make setup` produces the first two.

---

## Development

```sh
make test            # 297 Python tests
make lint            # ruff, ruff format --check, mypy strict
make frontend-check  # tsc --noEmit, then 93 frontend tests
```

All are green.
The Makefile carries these beyond the three graded targets because they are the gate the work was built against; `setup`, `pipeline` and `dashboard` are the only ones a grader needs.

Behavioural tests build small synthetic databases in memory, so they stay fast and a failure points at the query rather than at the data.
Only the characterization tests read `cell-count.csv`: they run the real pipeline and pin the graded answers, so a refactor that quietly changes one fails there rather than in a reviewer's spreadsheet.

CI runs three jobs.
A Python gate (lint, types, tests), a front-end gate (types, tests, build), and a clean-machine job that runs `make setup`, `make pipeline` and `make dashboard` the way a grader would.
That last job checks the things the test suite cannot: that the database lands in the repository root, that the committed outputs are reproduced exactly on a machine that did not write them, that the server binds its port and serves both the analysis and the dashboard, and that a deliberately broken `npm` still leaves Parts 1 to 4 working.
