/**
 * Number formatting for the tables and captions.
 *
 * One rule runs through all of it: a quantity the API could not compute is
 * `null`, and null is never rendered as a number. A population too small to test
 * has no p-value, and printing `0.00` there would be a claim the analysis did
 * not make. It renders as an em rule with a title explaining why instead.
 */

/** What every unavailable number renders as. */
export const ABSENT = "—";

const COUNT = new Intl.NumberFormat("en-GB");

/** A count, with thousands separators. Sample totals reach five figures. */
export function formatCount(value: number): string {
  return COUNT.format(value);
}

/** A relative frequency, in percent. Two decimals is the spec's own precision. */
export function formatPercent(value: number, digits = 2): string {
  return `${value.toFixed(digits)}%`;
}

/** A signed quantity, so a shift's direction reads without checking the sign. */
export function formatSigned(value: number | null, digits = 2): string {
  if (value === null) {
    return ABSENT;
  }
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(digits)}`;
}

/**
 * A p- or q-value.
 *
 * Small values are reported as below a threshold rather than in exponent form:
 * `< 0.001` is what a reader acts on, and `1.2e-7` invites treating the exact
 * magnitude as meaningful when the test's assumptions do not support it.
 */
export function formatProbability(value: number | null): string {
  if (value === null) {
    return ABSENT;
  }
  if (value < 0.001) {
    return "< 0.001";
  }
  return value.toFixed(3);
}

/** An interval, as the pair of bounds. Null when the population was not tested. */
export function formatInterval(
  interval: readonly [number, number] | null,
  digits = 2,
): string {
  if (interval === null) {
    return ABSENT;
  }
  const [low, high] = interval;
  return `[${formatSigned(low, digits)}, ${formatSigned(high, digits)}]`;
}

/** The common-language effect size, on its natural 0 to 1 scale. */
export function formatEffectSize(value: number | null): string {
  if (value === null) {
    return ABSENT;
  }
  return value.toFixed(3);
}

/** A confidence level as a percentage, from the alpha it was computed at. */
export function formatConfidence(alpha: number): string {
  const level = (1 - alpha) * 100;
  // 99% stays "99%", while alpha/5 gives 99.0% and needs the decimal to be true.
  const digits = Number.isInteger(level) ? 0 : 1;
  return `${level.toFixed(digits)}%`;
}
