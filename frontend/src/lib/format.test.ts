import { describe, expect, it } from "vitest";
import {
  ABSENT,
  formatConfidence,
  formatCount,
  formatEffectSize,
  formatInterval,
  formatPercent,
  formatProbability,
  formatSigned,
} from "./format";

describe("absent values", () => {
  it("never renders a missing statistic as a number", () => {
    // A population too small to test has no p-value. Printing 0.000 there, or
    // a shift of 0.00, would be a claim the analysis did not make.
    expect(formatProbability(null)).toBe(ABSENT);
    expect(formatSigned(null)).toBe(ABSENT);
    expect(formatInterval(null)).toBe(ABSENT);
    expect(formatEffectSize(null)).toBe(ABSENT);
  });

  it("still renders a genuine zero", () => {
    expect(formatSigned(0)).toBe("+0.00");
    expect(formatEffectSize(0)).toBe("0.000");
    expect(formatCount(0)).toBe("0");
  });
});

describe("formatProbability", () => {
  it("reports very small values as below a threshold", () => {
    expect(formatProbability(1.2e-7)).toBe("< 0.001");
    expect(formatProbability(0.0009)).toBe("< 0.001");
  });

  it("keeps three decimals where they mean something", () => {
    expect(formatProbability(0.001)).toBe("0.001");
    expect(formatProbability(0.0432)).toBe("0.043");
    expect(formatProbability(0.885)).toBe("0.885");
    expect(formatProbability(1)).toBe("1.000");
  });
});

describe("formatSigned", () => {
  it("always shows the direction, using a real minus sign", () => {
    expect(formatSigned(1.234)).toBe("+1.23");
    expect(formatSigned(-1.234)).toBe("−1.23");
  });
});

describe("formatInterval", () => {
  it("shows both bounds with their signs", () => {
    expect(formatInterval([-1.05, 0.87])).toBe("[−1.05, +0.87]");
  });

  it("keeps a wholly positive interval readable as such", () => {
    expect(formatInterval([0.4, 2.6])).toBe("[+0.40, +2.60]");
  });
});

describe("formatConfidence", () => {
  it("names the level a marginal interval covers", () => {
    expect(formatConfidence(0.05)).toBe("95%");
    expect(formatConfidence(0.01)).toBe("99%");
  });

  it("keeps the decimal when the simultaneous level needs one", () => {
    // alpha 0.05 over three tested populations. Rounding this to 98% would
    // misstate what the family-wise interval covers.
    expect(formatConfidence(0.05 / 3)).toBe("98.3%");
    expect(formatConfidence(0.05 / 5)).toBe("99%");
  });
});

describe("counts and percentages", () => {
  it("separates thousands, because sample totals reach five figures", () => {
    expect(formatCount(52500)).toBe("52,500");
  });

  it("keeps the spec's two decimal places on a relative frequency", () => {
    expect(formatPercent(9.5)).toBe("9.50%");
    expect(formatPercent(33.333333)).toBe("33.33%");
  });
});
