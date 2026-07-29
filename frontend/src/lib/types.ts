/** The shapes `src/cellcount/api.py` returns.
 *
 * Hand-written rather than generated, and deliberately narrow: `number | null`
 * where the API says `float | None`, so a null p-value cannot be formatted as
 * `0` by accident. Every optional field here is optional in the Python model
 * too, and the reason it is optional is worth knowing at the call site.
 */

/** The cohort a response was computed over, echoed back so a view can label it.
 *
 * `null` means unconstrained, not "missing". The distinction matters: a null
 * `treatment` is every treatment, and the form question's cohort relies on it.
 */
export interface CohortOut {
  condition: string | null;
  treatment: string | null;
  response: string | null;
  sex: string | null;
  sample_type: string | null;
  timepoints: number[] | null;
}

export interface FilterOptions {
  /** Cohort field name -> the values it can take, read out of the database. */
  fields: Record<string, string[]>;
  timepoints: number[];
  populations: string[];
  /** Columns `/api/comparison` will accept for `split_on`. */
  split_columns: string[];
  /** Where the dashboard opens, so the controls start where the statistics do. */
  default_cohort: CohortOut;
}

/** Part 2's row, with the spec's own column names. */
export interface SummaryRow {
  sample: string;
  total_count: number;
  population: string;
  count: number;
  percentage: number;
}

export interface SummaryPage {
  cohort: CohortOut;
  rows: SummaryRow[];
  /** Rows matching the cohort, before this page was cut out of them. */
  total: number;
  limit: number;
  offset: number;
}

export interface PopulationComparison {
  population: string;
  /** Group value -> sample count. Keys are the members of `groups`. */
  n: Record<string, number>;
  median: Record<string, number>;
  /** Every observation, per group. The boxplot is drawn from these. */
  values: Record<string, number[]>;
  /** Null when the group was too small to test, which is not the same as 1. */
  p_value: number | null;
  /** Benjamini-Hochberg across the tested populations. This decides significance. */
  q_value: number | null;
  /** Hodges-Lehmann shift in percentage points; positive means `groups[0]` higher. */
  shift: number | null;
  /** Interval for this population alone, at `alpha`. */
  shift_ci: [number, number] | null;
  /** Interval covering the whole family, at `simultaneous_alpha`. */
  simultaneous_ci: [number, number] | null;
  /** P(x > y) + 0.5 P(x = y) for x in `groups[0]`. 0.5 means no separation. */
  effect_size: number | null;
}

export interface Comparison {
  cohort: CohortOut;
  split_on: string;
  /** Sorted, so `groups[0]` is the reference every signed quantity points away from. */
  groups: string[];
  n_samples: Record<string, number>;
  n_subjects: Record<string, number>;
  /**
   * True when a subject contributed more than one sample.
   *
   * The single most important caveat in the analysis: the rank test assumes
   * independent observations, and pooled timepoints are not independent, so the
   * p-values are optimistic. The banner that says so is driven by this field.
   */
  repeated_measures: boolean;
  /** How many populations entered the correction. A q-value means nothing without it. */
  n_tested: number;
  alpha: number;
  /** The level each `simultaneous_ci` was computed at: `alpha / n_tested`. */
  simultaneous_alpha: number;
  populations: PopulationComparison[];
}

export interface Subsets {
  cohort: CohortOut;
  /** Samples, as Part 4 words that question. */
  samples_per_project: Record<string, number>;
  /** Distinct subjects. The counting grain differs from the row above it. */
  subjects_per_response: Record<string, number>;
  subjects_per_sex: Record<string, number>;
}

export interface MeanCount {
  cohort: CohortOut;
  population: string;
  /** Null when the cohort matched nothing. Zero would be a real mean. */
  mean_count: number | null;
}
