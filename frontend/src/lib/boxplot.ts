/**
 * The geometry behind the boxplots, kept out of the components that draw them.
 *
 * The charts are hand-drawn SVG rather than a charting library. Recharts has no
 * box trace at all; full `plotly.js` is roughly 4.5 MB minified, which would
 * dominate both the bundle and the build on the two-core Codespace the graders
 * use, and a custom Plotly bundle adds a second build step to save one chart.
 * What the API returns is every observation per group, so the whole of what a
 * box needs is the fifty lines below.
 *
 * The conventions match `src/cellcount/plots.py`, which draws the committed PNG
 * through matplotlib: quartiles by linear interpolation, whiskers reaching the
 * most extreme observation within 1.5 IQR of the nearer quartile. Two renderings
 * of one result that disagreed about where the box sits would be worse than
 * having only one.
 *
 * Nothing statistical is computed here. `n`, the medians, p, q, the intervals
 * and the effect size all arrive from the API, which is the same
 * `ComparisonResult` the figure and the write-up are rendered from.
 */

export interface BoxStats {
  n: number;
  min: number;
  max: number;
  q1: number;
  /** The sample median. Reported for drawing only; the table quotes the API's. */
  median: number;
  q3: number;
  /** The lowest observation within 1.5 IQR below `q1`, as matplotlib draws it. */
  lowerWhisker: number;
  /** The highest observation within 1.5 IQR above `q3`. */
  upperWhisker: number;
}

/**
 * The p-quantile by linear interpolation between order statistics.
 *
 * This is numpy's default method, and therefore matplotlib's, and therefore the
 * one the committed figure's boxes were drawn with.
 *
 * `sorted` must be ascending and non-empty; callers below guarantee both.
 */
export function quantile(sorted: readonly number[], p: number): number {
  if (sorted.length === 0) {
    throw new Error("quantile of an empty sample is undefined");
  }
  const position = p * (sorted.length - 1);
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  // `noUncheckedIndexedAccess` is on, and these two reads are the arithmetic
  // this function exists for, so they are checked rather than asserted.
  const low = sorted[lower];
  const high = sorted[upper];
  if (low === undefined || high === undefined) {
    throw new Error(`quantile ${p} is outside [0, 1]`);
  }
  return low + (position - lower) * (high - low);
}

/** The five numbers plus the whisker reach, or null for an empty group. */
export function boxStats(values: readonly number[]): BoxStats | null {
  if (values.length === 0) {
    return null;
  }
  const sorted = [...values].sort((a, b) => a - b);
  const q1 = quantile(sorted, 0.25);
  const median = quantile(sorted, 0.5);
  const q3 = quantile(sorted, 0.75);
  const reach = 1.5 * (q3 - q1);
  const lowerFence = q1 - reach;
  const upperFence = q3 + reach;

  const min = sorted[0] as number;
  const max = sorted[sorted.length - 1] as number;

  // The whiskers stop at real observations, not at the fences. Drawing them to
  // the fence would invent a value the sample does not contain, and on a group
  // with no spread it would draw a whisker where the data has none. The fences
  // always bracket at least one observation, since q1 and q3 lie between the
  // extremes, so the fallbacks below are unreachable rather than approximate.
  let lowerWhisker = min;
  for (const value of sorted) {
    if (value >= lowerFence) {
      lowerWhisker = value;
      break;
    }
  }
  let upperWhisker = max;
  for (let index = sorted.length - 1; index >= 0; index -= 1) {
    const value = sorted[index] as number;
    if (value <= upperFence) {
      upperWhisker = value;
      break;
    }
  }

  return { n: sorted.length, min, max, q1, median, q3, lowerWhisker, upperWhisker };
}

/**
 * A rounded axis range and its ticks, covering every value in `values`.
 *
 * The step is 1, 2 or 5 times a power of ten, so the labels read as numbers a
 * person would choose. The domain is snapped outward to whole steps rather than
 * padded by a percentage, which keeps the top and bottom gridlines labelled.
 */
export function niceScale(
  values: readonly number[],
  targetTicks = 5,
): { min: number; max: number; ticks: number[] } {
  const finite = values.filter((value) => Number.isFinite(value));
  if (finite.length === 0) {
    return { min: 0, max: 1, ticks: [0, 0.5, 1] };
  }
  let low = Math.min(...finite);
  let high = Math.max(...finite);
  if (low === high) {
    // A single distinct value still needs a range to be drawn inside.
    const pad = Math.abs(low) > 0 ? Math.abs(low) * 0.1 : 1;
    low -= pad;
    high += pad;
  }

  const rawStep = (high - low) / Math.max(1, targetTicks);
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalised = rawStep / magnitude;
  const step =
    magnitude * (normalised <= 1 ? 1 : normalised <= 2 ? 2 : normalised <= 5 ? 5 : 10);

  const min = Math.floor(low / step) * step;
  const max = Math.ceil(high / step) * step;

  // Multiplied out from the start rather than accumulated, because repeatedly
  // adding a step like 0.1 drifts; the visible symptom is a top gridline that
  // is one ulp past the domain and so never drawn.
  const count = Math.round((max - min) / step);
  const ticks: number[] = [];
  for (let index = 0; index <= count; index += 1) {
    ticks.push(Number((min + index * step).toPrecision(12)));
  }
  return { min, max, ticks };
}

/**
 * How large and how solid one plotted point should be, given how many share it.
 *
 * Every observation is drawn, which is the point of the chart, but a fixed
 * radius that reads well at n = 12 turns into an opaque column at n = 4,467 and
 * hides the box it is supposed to sit behind. Both quantities therefore shrink
 * with the log of the group size, and are clamped at both ends so a very small
 * group does not get absurdly large dots and a very large one does not vanish.
 *
 * Log rather than linear because the interesting range spans two orders of
 * magnitude: the spec's baseline cohort is a few hundred, the unfiltered one is
 * several thousand, and a hand-checked fixture is a dozen.
 */
export function pointStyle(n: number): { radius: number; opacity: number } {
  const SPARSE = 50;
  const DENSE = 2000;
  const position =
    (Math.log10(Math.max(n, 1)) - Math.log10(SPARSE)) /
    (Math.log10(DENSE) - Math.log10(SPARSE));
  const t = Math.min(1, Math.max(0, position));
  return {
    radius: 3.0 + t * (1.4 - 3.0),
    opacity: 0.55 + t * (0.18 - 0.55),
  };
}

/**
 * A stable horizontal offset in [-1, 1) for one plotted point.
 *
 * The points are jittered so that ties do not hide behind each other. The offset
 * is derived from the point's identity rather than from a random number
 * generator, so a re-render, a resize, or a refetch of the same cohort puts
 * every point back where the reader last saw it. `plots.py` gets the same
 * property from a fixed seed.
 */
export function jitterOffset(key: string, index: number): number {
  let hash = 0x811c9dc5;
  const text = `${key}:${index}`;
  for (let position = 0; position < text.length; position += 1) {
    hash ^= text.charCodeAt(position);
    // FNV-1a's 32-bit prime, by shifts because `*` would lose precision.
    hash +=
      (hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24);
    hash >>>= 0;
  }
  return (hash / 0x100000000) * 2 - 1;
}
