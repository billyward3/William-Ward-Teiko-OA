import { describeCohort } from "../lib/cohort";
import { formatCount } from "../lib/format";
import type { Subsets } from "../lib/types";
import type { Resource } from "../lib/useResource";
import { Section } from "./Section";

/**
 * Part 4: how the filtered subset breaks down.
 *
 * The counting unit is not the same in all three tables, and that is the spec's
 * wording rather than an inconsistency: it asks how many *samples* come from
 * each project, and how many *subjects* were responders or male. Every heading
 * therefore names its unit, because in this dataset the two happen to coincide
 * at baseline and a reader could otherwise reasonably assume they always do.
 */
export function SubsetsSection({
  resource,
}: {
  resource: Resource<Subsets>;
}): React.JSX.Element {
  const subsets = resource.data;

  return (
    <Section
      id="part-4"
      part="Part 4"
      title="Breakdown of the filtered subset"
      description="Counts within the cohort selected above. With the spec's filters this is melanoma PBMC samples at baseline from miraclib-treated patients."
      status={resource.status}
      error={resource.error}
      subtitle={subsets ? describeCohort(subsets.cohort) : undefined}
    >
      {subsets === null ? null : (
        <div className="breakdowns">
          <Breakdown
            title="Samples per project"
            unit="samples"
            counts={subsets.samples_per_project}
          />
          <Breakdown
            title="Subjects by response"
            unit="subjects"
            counts={subsets.subjects_per_response}
          />
          <Breakdown
            title="Subjects by sex"
            unit="subjects"
            counts={subsets.subjects_per_sex}
          />
        </div>
      )}
    </Section>
  );
}

/**
 * One breakdown, as counts with a proportional bar.
 *
 * A category the cohort matched none of is shown as zero rather than omitted.
 * `prj2` contributes no melanoma miraclib PBMC sample at all, and a chart that
 * simply dropped it would read as though the project did not exist.
 */
function Breakdown({
  title,
  unit,
  counts,
}: {
  title: string;
  unit: string;
  counts: Record<string, number>;
}): React.JSX.Element {
  const entries = Object.entries(counts);
  const total = entries.reduce((sum, [, value]) => sum + value, 0);
  const largest = entries.reduce((peak, [, value]) => Math.max(peak, value), 0);

  return (
    <div className="breakdown">
      <h3>{title}</h3>
      <p className="breakdown__total">
        {formatCount(total)} {unit} in total
      </p>
      <table className="data-table data-table--compact">
        <caption className="sr-only">
          {title}, counted in {unit}
        </caption>
        <thead>
          <tr>
            <th scope="col">category</th>
            <th scope="col" className="numeric">
              {unit}
            </th>
            <th scope="col" className="numeric">
              share
            </th>
            <th scope="col" aria-label="proportion" />
          </tr>
        </thead>
        <tbody>
          {entries.map(([category, value]) => (
            <tr key={category}>
              <th scope="row">{category}</th>
              <td className="numeric">{formatCount(value)}</td>
              <td className="numeric">
                {total === 0 ? "—" : `${((value / total) * 100).toFixed(1)}%`}
              </td>
              <td className="bar-cell">
                <span
                  className="bar"
                  style={{
                    width: largest === 0 ? "0%" : `${(value / largest) * 100}%`,
                  }}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
