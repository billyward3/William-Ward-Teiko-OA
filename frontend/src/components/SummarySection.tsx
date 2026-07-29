import { describeCohort } from "../lib/cohort";
import { formatCount, formatPercent } from "../lib/format";
import type { SummaryPage } from "../lib/types";
import type { Resource } from "../lib/useResource";
import { Section } from "./Section";

/**
 * Part 2: relative frequency per sample and population, paginated by the server.
 *
 * The page is cut out by SQL, not by the browser. Unfiltered this table is
 * 52,500 rows and roughly 6.6 MB of JSON, so fetching it whole to slice it
 * client-side would be slow on the first load and pointless on every one after.
 * `total` comes back with each page, so the reader can still see how large the
 * cohort is without the rows being sent.
 */
export const PAGE_SIZES = [50, 100, 250, 500, 1000] as const;

export interface SummarySectionProps {
  resource: Resource<SummaryPage>;
  limit: number;
  offset: number;
  onOffsetChange: (offset: number) => void;
  onLimitChange: (limit: number) => void;
}

export function SummarySection({
  resource,
  limit,
  offset,
  onOffsetChange,
  onLimitChange,
}: SummarySectionProps): React.JSX.Element {
  const page = resource.data;
  const total = page?.total ?? 0;
  const shown = page?.rows.length ?? 0;
  const first = total === 0 ? 0 : offset + 1;
  const last = offset + shown;

  return (
    <Section
      id="part-2"
      part="Part 2"
      title="Relative frequency of each population"
      description="One row per sample and population. The percentage is that population's count as a share of the sample's own total across all five populations."
      status={resource.status}
      error={resource.error}
      subtitle={page ? describeCohort(page.cohort) : undefined}
      controls={
        <label className="inline-field">
          <span>Rows per page</span>
          <select
            value={limit}
            onChange={(event) => {
              onLimitChange(Number(event.target.value));
            }}
          >
            {PAGE_SIZES.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
      }
    >
      {page === null ? null : (
        <>
          <div className="pager">
            <p className="pager__count">
              {total === 0
                ? "No rows match this cohort."
                : `Rows ${formatCount(first)}–${formatCount(last)} of ${formatCount(total)}`}
            </p>
            <div className="pager__buttons">
              <button
                type="button"
                onClick={() => {
                  onOffsetChange(Math.max(0, offset - limit));
                }}
                disabled={offset === 0}
              >
                Previous
              </button>
              <button
                type="button"
                onClick={() => {
                  onOffsetChange(offset + limit);
                }}
                disabled={last >= total}
              >
                Next
              </button>
            </div>
          </div>

          <div className="table-scroll table-scroll--tall">
            <table className="data-table">
              <caption className="sr-only">
                Relative frequency of each immune cell population, one row per
                sample and population
              </caption>
              <thead>
                <tr>
                  <th scope="col">sample</th>
                  <th scope="col" className="numeric">
                    total_count
                  </th>
                  <th scope="col">population</th>
                  <th scope="col" className="numeric">
                    count
                  </th>
                  <th scope="col" className="numeric">
                    percentage
                  </th>
                </tr>
              </thead>
              <tbody>
                {page.rows.map((row) => (
                  <tr key={`${row.sample}-${row.population}`}>
                    <th scope="row">{row.sample}</th>
                    <td className="numeric">{formatCount(row.total_count)}</td>
                    <td>{row.population}</td>
                    <td className="numeric">{formatCount(row.count)}</td>
                    <td className="numeric">{formatPercent(row.percentage)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Section>
  );
}
