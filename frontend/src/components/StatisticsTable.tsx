import {
  ABSENT,
  formatConfidence,
  formatCount,
  formatEffectSize,
  formatInterval,
  formatPercent,
  formatProbability,
  formatSigned,
} from "../lib/format";
import type { Comparison } from "../lib/types";
import { groupColour } from "./Boxplot";

/**
 * Every number behind the boxplots, in one table.
 *
 * It is also the charts' accessible twin: nothing on this page is legible only
 * as a picture. Every column is a field of the API's response, and none of them
 * is recomputed here.
 *
 * The two intervals are shown side by side deliberately. `shift_ci` covers one
 * population at alpha; a reader who takes five of those and says "no population
 * shifts by more than the widest of them" has made a joint claim that level does
 * not support. `simultaneous_ci` is the one that does.
 */
export function StatisticsTable({
  comparison,
}: {
  comparison: Comparison;
}): React.JSX.Element {
  const { groups, split_on: splitOn, alpha } = comparison;

  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption className="sr-only">
          Mann-Whitney comparison of relative frequency between {splitOn} groups,
          one row per population
        </caption>
        <thead>
          <tr>
            <th scope="col">Population</th>
            {groups.map((group, index) => (
              <th scope="col" key={`n-${group}`} className="numeric">
                <span
                  className="swatch"
                  style={{ background: groupColour(index) }}
                  aria-hidden="true"
                />
                n · {group}
              </th>
            ))}
            {groups.map((group) => (
              <th scope="col" key={`median-${group}`} className="numeric">
                median · {group}
              </th>
            ))}
            <th
              scope="col"
              className="numeric"
              title={`Hodges-Lehmann estimate in percentage points. Positive means ${groups[0] ?? "the first group"} is higher.`}
            >
              shift (pp)
            </th>
            <th scope="col" className="numeric">
              {formatConfidence(alpha)} CI
            </th>
            <th
              scope="col"
              className="numeric"
              title="Computed at alpha divided by the number of populations tested, so the five intervals hold jointly."
            >
              {formatConfidence(comparison.simultaneous_alpha)} CI, family-wise
            </th>
            <th scope="col" className="numeric">
              p
            </th>
            <th
              scope="col"
              className="numeric"
              title={`Benjamini-Hochberg across the ${String(comparison.n_tested)} populations tested. This is what decides significance.`}
            >
              q
            </th>
            <th
              scope="col"
              className="numeric"
              title="Common-language effect size. 0.5 means no separation."
            >
              P({groups[0] ?? "a"} &gt; {groups[1] ?? "b"})
            </th>
          </tr>
        </thead>
        <tbody>
          {comparison.populations.map((population) => {
            const significant =
              population.q_value !== null && population.q_value < alpha;
            return (
              <tr key={population.population}>
                <th scope="row">
                  {population.population}
                  {significant && <span className="badge">significant</span>}
                  {population.q_value === null && (
                    <span
                      className="badge badge--quiet"
                      title="Too few samples in one group for a rank test to be able to reach any p-value below alpha."
                    >
                      not tested
                    </span>
                  )}
                </th>
                {groups.map((group) => (
                  <td className="numeric" key={`n-${group}`}>
                    {formatCount(population.n[group] ?? 0)}
                  </td>
                ))}
                {groups.map((group) => {
                  const median = population.median[group];
                  return (
                    <td className="numeric" key={`median-${group}`}>
                      {median === undefined ? ABSENT : formatPercent(median)}
                    </td>
                  );
                })}
                <td className="numeric">{formatSigned(population.shift)}</td>
                <td className="numeric">{formatInterval(population.shift_ci)}</td>
                <td className="numeric">
                  {formatInterval(population.simultaneous_ci)}
                </td>
                <td className="numeric">
                  {formatProbability(population.p_value)}
                </td>
                <td className="numeric">
                  {formatProbability(population.q_value)}
                </td>
                <td className="numeric">
                  {formatEffectSize(population.effect_size)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
