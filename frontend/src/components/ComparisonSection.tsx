import { describeCohort } from "../lib/cohort";
import { formatConfidence } from "../lib/format";
import type { Comparison, FilterOptions } from "../lib/types";
import type { Resource } from "../lib/useResource";
import { Boxplot, groupColour } from "./Boxplot";
import { IndependenceNote } from "./IndependenceNote";
import { Section } from "./Section";
import { StatisticsTable } from "./StatisticsTable";

/**
 * Part 3: relative frequency by group, as pictures and as numbers.
 *
 * The split column is a control rather than a constant. Response is what the
 * spec asks about, but the API will split on any cohort field, and the question
 * "does this differ by sex instead?" is one click rather than one deployment.
 */
export interface ComparisonSectionProps {
  resource: Resource<Comparison>;
  options: FilterOptions;
  splitOn: string;
  onSplitOnChange: (splitOn: string) => void;
}

export function ComparisonSection({
  resource,
  options,
  splitOn,
  onSplitOnChange,
}: ComparisonSectionProps): React.JSX.Element {
  const comparison = resource.data;

  return (
    <Section
      id="part-3"
      part="Part 3"
      // Driven by the split column, because it is a control. A fixed
      // "Responders against non-responders" would still be sitting above the
      // charts after someone split on sex.
      title={`Relative frequency by ${comparison?.split_on ?? splitOn}`}
      description="Part 3 asks about responders against non-responders; any cohort field can be substituted below. Mann-Whitney U per population, corrected across the populations tested. Every observation is drawn, and each group's size is written under its box."
      status={resource.status}
      error={resource.error}
      subtitle={comparison ? describeCohort(comparison.cohort) : undefined}
      controls={
        <label className="inline-field">
          <span>Split on</span>
          <select
            value={splitOn}
            onChange={(event) => {
              onSplitOnChange(event.target.value);
            }}
          >
            {options.split_columns.map((column) => (
              <option key={column} value={column}>
                {column}
              </option>
            ))}
          </select>
        </label>
      }
    >
      {comparison === null ? null : comparison.groups.length < 2 ? (
        <p className="empty">
          No samples matched this cohort, so there is nothing to compare.
        </p>
      ) : (
        <>
          <IndependenceNote comparison={comparison} />

          <div className="legend">
            {comparison.groups.map((group, index) => (
              <span className="legend__item" key={group}>
                <span
                  className="swatch"
                  style={{ background: groupColour(index) }}
                  aria-hidden="true"
                />
                {comparison.split_on} = {group}
              </span>
            ))}
            <span className="legend__unit">relative frequency (%)</span>
          </div>

          <div className="boxplot-grid">
            {comparison.populations.map((population) => (
              <Boxplot
                key={population.population}
                comparison={population}
                groups={comparison.groups}
                splitOn={comparison.split_on}
              />
            ))}
          </div>

          <StatisticsTable comparison={comparison} />

          <ul className="footnotes">
            <li>
              Significance is judged by <strong>q</strong>, the
              Benjamini-Hochberg adjusted p-value across the{" "}
              {comparison.n_tested} populations that could be tested at
              alpha&nbsp;=&nbsp;{comparison.alpha}. Whether an interval covers
              zero is not the same test: the {formatConfidence(comparison.alpha)}{" "}
              interval is not adjusted, and the{" "}
              {formatConfidence(comparison.simultaneous_alpha)} one is the column
              that supports a claim about all of them at once.
            </li>
            <li>
              The five frequencies are shares of one sample total, so they sum to
              100% by construction. A population that rises forces the others to
              fall, which means these five results are not five independent
              findings.
            </li>
            <li>
              Mann-Whitney tests stochastic dominance. It is a test of medians
              only when the two distributions have the same shape, which is why
              the shift estimate and its interval are reported beside it.
            </li>
          </ul>
        </>
      )}
    </Section>
  );
}
