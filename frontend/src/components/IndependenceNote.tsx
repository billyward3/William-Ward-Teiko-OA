import { formatCount } from "../lib/format";
import type { Comparison } from "../lib/types";

/**
 * The independence caveat, driven by the API's `repeated_measures` field.
 *
 * This is the most important thing on the page, so it is stated where the reader
 * cannot miss it rather than in a footnote. Nothing here is hardcoded: the flag,
 * both counts and the split column all come from the response, so a cohort that
 * pools timepoints raises the warning and a cohort that does not lowers it,
 * without either sentence being written twice.
 *
 * The reason it matters: Mann-Whitney assumes independent observations. In this
 * trial every subject contributes three samples, so a cohort spanning timepoints
 * counts each subject up to three times. That inflates the effective sample
 * size, which makes the p-values smaller than they should be and the intervals
 * narrower than they should be. The fix is a click away, which is why the note
 * says so.
 */
export function IndependenceNote({
  comparison,
}: {
  comparison: Comparison;
}): React.JSX.Element | null {
  const samples = total(comparison.n_samples);
  const subjects = total(comparison.n_subjects);
  if (subjects === 0) {
    return null;
  }

  if (!comparison.repeated_measures) {
    return (
      <p className="note note--ok" role="note">
        <strong>Observations are independent.</strong>{" "}
        {formatCount(samples)} samples from {formatCount(subjects)} subjects, one
        each, so the rank test&rsquo;s independence assumption holds for this
        cohort.
      </p>
    );
  }

  return (
    <p className="note note--warn" role="note">
      <strong>Repeated measures: these observations are not independent.</strong>{" "}
      This cohort has {formatCount(samples)} samples from only{" "}
      {formatCount(subjects)} subjects, so some subjects are counted more than
      once. Mann-Whitney assumes independent observations, so the p- and q-values
      below are optimistic and the intervals are narrower than the data supports.
      Restricting to a single day removes the problem.
    </p>
  );
}

function total(counts: Record<string, number>): number {
  return Object.values(counts).reduce((sum, value) => sum + value, 0);
}
