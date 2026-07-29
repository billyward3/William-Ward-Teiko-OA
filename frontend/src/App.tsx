import { useCallback, useMemo, useState } from "react";
import { ComparisonSection } from "./components/ComparisonSection";
import { FilterPanel } from "./components/FilterPanel";
import { SubsetsSection } from "./components/SubsetsSection";
import { SummarySection } from "./components/SummarySection";
import { fetchComparison, fetchFilters, fetchSubsets, fetchSummary } from "./lib/api";
import { selectionFrom, type CohortSelection } from "./lib/cohort";
import type { FilterOptions } from "./lib/types";
import { useResource } from "./lib/useResource";

/**
 * The dashboard.
 *
 * Interactive in the sense the spec asks for: choosing a cohort re-runs the
 * analysis on the server against that cohort, rather than re-rendering a file
 * that was computed once. Every number on the page comes back from `/api`, and
 * the page recomputes nothing.
 *
 * The filter options load first because they decide what the controls can offer
 * and where the page opens, so everything below waits on them. Once loaded they
 * never change, which is why they are fetched once and passed down.
 */
const DEFAULT_SPLIT_ON = "response";
const DEFAULT_ALPHA = 0.05;
const DEFAULT_PAGE_SIZE = 100;

export function App(): React.JSX.Element {
  const loadFilters = useCallback(
    (signal: AbortSignal) => fetchFilters(signal),
    [],
  );
  const filters = useResource<FilterOptions>(loadFilters);

  return (
    <div className="app">
      <PageHeader />
      {filters.data === null ? (
        <div className="panel">
          {filters.error === null ? (
            <p className="empty">Loading the cohort options…</p>
          ) : (
            <>
              <p className="error" role="alert">
                {filters.error}
              </p>
              <p className="empty">
                The dashboard could not reach the analysis API. If the database
                has not been built yet, run <code>make pipeline</code> and
                reload.
              </p>
            </>
          )}
        </div>
      ) : (
        <Dashboard options={filters.data} />
      )}
      <PageFooter />
    </div>
  );
}

function Dashboard({ options }: { options: FilterOptions }): React.JSX.Element {
  const specCohort = useMemo(
    () => selectionFrom(options.default_cohort),
    [options],
  );
  const [selection, setSelection] = useState<CohortSelection>(specCohort);
  const [splitOn, setSplitOn] = useState(
    options.split_columns.includes(DEFAULT_SPLIT_ON)
      ? DEFAULT_SPLIT_ON
      : (options.split_columns[0] ?? DEFAULT_SPLIT_ON),
  );
  const [limit, setLimit] = useState(DEFAULT_PAGE_SIZE);
  const [offset, setOffset] = useState(0);

  // Paging is reset here rather than in an effect watching the cohort. An effect
  // would fetch twice on every filter change: once for the old offset, then
  // again for zero, briefly showing rows from a page the new cohort may not have.
  const changeSelection = useCallback((next: CohortSelection) => {
    setSelection(next);
    setOffset(0);
  }, []);

  const changeLimit = useCallback((next: number) => {
    setLimit(next);
    setOffset(0);
  }, []);

  const loadSummary = useCallback(
    (signal: AbortSignal) => fetchSummary(selection, { limit, offset }, signal),
    [selection, limit, offset],
  );
  const loadComparison = useCallback(
    (signal: AbortSignal) =>
      fetchComparison(selection, { splitOn, alpha: DEFAULT_ALPHA }, signal),
    [selection, splitOn],
  );
  const loadSubsets = useCallback(
    (signal: AbortSignal) => fetchSubsets(selection, signal),
    [selection],
  );

  const summary = useResource(loadSummary);
  const comparison = useResource(loadComparison);
  const subsets = useResource(loadSubsets);

  const busy =
    summary.status === "loading" ||
    comparison.status === "loading" ||
    subsets.status === "loading";

  return (
    <>
      <FilterPanel
        options={options}
        selection={selection}
        onChange={changeSelection}
        specCohort={specCohort}
        busy={busy}
      />
      <SummarySection
        resource={summary}
        limit={limit}
        onOffsetChange={setOffset}
        onLimitChange={changeLimit}
      />
      <ComparisonSection
        resource={comparison}
        options={options}
        splitOn={splitOn}
        onSplitOnChange={setSplitOn}
      />
      <SubsetsSection resource={subsets} />
    </>
  );
}

function PageHeader(): React.JSX.Element {
  return (
    <header className="page-header">
      <h1>Loblaw Bio cell counts</h1>
      <p className="lead">
        Immune cell population frequencies for the miraclib trial. Choose a
        cohort and the analysis is recomputed against it; nothing on this page is
        a stored result.
      </p>
      <nav aria-label="Sections">
        <a href="#part-2">Part 2 · frequencies</a>
        <a href="#part-3">Part 3 · responders</a>
        <a href="#part-4">Part 4 · subsets</a>
        <a href="/docs">API reference</a>
      </nav>
    </header>
  );
}

function PageFooter(): React.JSX.Element {
  return (
    <footer className="page-footer">
      <p>
        Every figure is computed by the same library the committed outputs are
        generated from, so the dashboard and <code>outputs/</code> cannot
        disagree.
      </p>
    </footer>
  );
}
