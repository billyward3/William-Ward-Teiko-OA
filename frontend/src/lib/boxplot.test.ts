import { describe, expect, it } from "vitest";
import { boxStats, jitterOffset, niceScale, pointStyle, quantile } from "./boxplot";

/**
 * The expectations below were computed with numpy and cross-checked against
 * `matplotlib.cbook.boxplot_stats`, which is what draws the committed PNG. They
 * are written as literals rather than derived here, so a change in either
 * renderer's convention breaks this file rather than passing quietly.
 *
 * The main sample is geometric and unevenly spaced on purpose. Both quartiles
 * fall between observations, so an implementation that picks the nearest order
 * statistic instead of interpolating gets 2 and 32 rather than 3 and 24, and the
 * top value is far enough out to be a flier, so the upper whisker is not the
 * maximum. An evenly spaced or symmetric sample would hide all three mistakes.
 */
const GEOMETRIC = [1, 2, 4, 8, 16, 32, 64];

describe("quantile", () => {
  it("interpolates linearly between order statistics, as numpy does", () => {
    expect(quantile(GEOMETRIC, 0.25)).toBe(3);
    expect(quantile(GEOMETRIC, 0.5)).toBe(8);
    expect(quantile(GEOMETRIC, 0.75)).toBe(24);
  });

  it("interpolates on an even-sized sample, where no quartile is a member", () => {
    const sample = [3, 5, 6, 9];
    expect(quantile(sample, 0.25)).toBeCloseTo(4.5, 12);
    expect(quantile(sample, 0.5)).toBeCloseTo(5.5, 12);
    expect(quantile(sample, 0.75)).toBeCloseTo(6.75, 12);
  });

  it("returns the endpoints at 0 and 1", () => {
    expect(quantile(GEOMETRIC, 0)).toBe(1);
    expect(quantile(GEOMETRIC, 1)).toBe(64);
  });

  it("refuses an empty sample rather than returning NaN", () => {
    expect(() => quantile([], 0.5)).toThrow(/empty/);
  });
});

describe("boxStats", () => {
  it("stops the whisker at the last observation inside the fence", () => {
    const stats = boxStats(GEOMETRIC);
    expect(stats).not.toBeNull();
    if (stats === null) return;

    expect(stats.q1).toBe(3);
    expect(stats.median).toBe(8);
    expect(stats.q3).toBe(24);
    // IQR is 21, so the upper fence is 55.5 and 64 sits outside it.
    expect(stats.upperWhisker).toBe(32);
    expect(stats.max).toBe(64);
    // Nothing is below the lower fence, so that whisker does reach the minimum.
    expect(stats.lowerWhisker).toBe(1);
    expect(stats.min).toBe(1);
    expect(stats.n).toBe(7);
  });

  it("reaches both extremes when no observation is a flier", () => {
    const stats = boxStats([3, 5, 6, 9]);
    expect(stats?.lowerWhisker).toBe(3);
    expect(stats?.upperWhisker).toBe(9);
  });

  it("collapses to the value when the sample has no spread", () => {
    // IQR is zero, so both fences sit on the value. Whiskers drawn to the fence
    // rather than to an observation would be identical here; whiskers drawn to
    // q1 and q3 as a fallback would not.
    const stats = boxStats([7, 7, 7, 7, 7]);
    expect(stats).toEqual({
      n: 5,
      min: 7,
      max: 7,
      q1: 7,
      median: 7,
      q3: 7,
      lowerWhisker: 7,
      upperWhisker: 7,
    });
  });

  it("handles a single observation", () => {
    const stats = boxStats([2.5]);
    expect(stats?.n).toBe(1);
    expect(stats?.median).toBe(2.5);
    expect(stats?.lowerWhisker).toBe(2.5);
    expect(stats?.upperWhisker).toBe(2.5);
  });

  it("is null for an empty group rather than a box at zero", () => {
    expect(boxStats([])).toBeNull();
  });

  it("does not reorder the caller's array", () => {
    const values = [5, 1, 3];
    boxStats(values);
    expect(values).toEqual([5, 1, 3]);
  });
});

describe("niceScale", () => {
  it("rounds the domain outward to whole steps", () => {
    expect(niceScale(GEOMETRIC)).toEqual({
      min: 0,
      max: 80,
      ticks: [0, 20, 40, 60, 80],
    });
  });

  it("covers every value it was given", () => {
    const values = [0.37, 1.02, 4.8, 4.81];
    const scale = niceScale(values);
    expect(scale.min).toBeLessThanOrEqual(Math.min(...values));
    expect(scale.max).toBeGreaterThanOrEqual(Math.max(...values));
  });

  it("produces evenly spaced ticks free of floating point dust", () => {
    const { ticks } = niceScale([0.51, 0.92]);
    expect(ticks.length).toBeGreaterThan(1);
    const steps = ticks.slice(1).map((tick, index) => tick - (ticks[index] ?? 0));
    for (const step of steps) {
      expect(step).toBeCloseTo(steps[0] ?? 0, 10);
    }
    // Rendered straight into the SVG, so 0.7000000000000001 would be visible.
    for (const tick of ticks) {
      expect(String(tick).length).toBeLessThan(8);
    }
  });

  it("gives a single distinct value a range to be drawn inside", () => {
    const scale = niceScale([5, 5, 5]);
    expect(scale.min).toBeLessThan(5);
    expect(scale.max).toBeGreaterThan(5);
  });

  it("falls back to a unit range when there is nothing to scale", () => {
    expect(niceScale([]).ticks.length).toBeGreaterThan(1);
  });
});

describe("pointStyle", () => {
  it("shrinks and fades as the group grows", () => {
    // The unfiltered cohort has 4,467 in one group and the spec's baseline has
    // 325. Drawn at the same weight, the larger one is an opaque column that
    // hides the box the points are supposed to sit behind.
    const small = pointStyle(12);
    const medium = pointStyle(325);
    const large = pointStyle(4467);

    expect(small.radius).toBeGreaterThan(medium.radius);
    expect(medium.radius).toBeGreaterThan(large.radius);
    expect(small.opacity).toBeGreaterThan(medium.opacity);
    expect(medium.opacity).toBeGreaterThan(large.opacity);
  });

  it("clamps at both ends rather than running away", () => {
    // Without the clamp a 3-point group gets a radius wider than the box, and a
    // 50,000-point one gets a negative radius, which SVG silently drops.
    expect(pointStyle(1)).toEqual(pointStyle(50));
    expect(pointStyle(2000)).toEqual(pointStyle(50000));
    expect(pointStyle(0).radius).toBeGreaterThan(0);
  });

  it("stays visible and inside the jitter width at every size", () => {
    for (const n of [1, 4, 12, 100, 656, 4467, 100000]) {
      const { radius, opacity } = pointStyle(n);
      expect(radius).toBeGreaterThan(1);
      expect(radius).toBeLessThan(5);
      expect(opacity).toBeGreaterThan(0.1);
      expect(opacity).toBeLessThanOrEqual(1);
    }
  });
});

describe("jitterOffset", () => {
  it("returns the same offset for the same point every time", () => {
    expect(jitterOffset("b_cell-yes", 3)).toBe(jitterOffset("b_cell-yes", 3));
  });

  it("separates points that differ only by index or by group", () => {
    expect(jitterOffset("b_cell-yes", 3)).not.toBe(jitterOffset("b_cell-yes", 4));
    expect(jitterOffset("b_cell-yes", 3)).not.toBe(jitterOffset("b_cell-no", 3));
  });

  it("stays inside the half-open unit interval", () => {
    for (let index = 0; index < 200; index += 1) {
      const offset = jitterOffset("nk_cell-no", index);
      expect(offset).toBeGreaterThanOrEqual(-1);
      expect(offset).toBeLessThan(1);
    }
  });

  it("spreads points rather than stacking them on a few offsets", () => {
    const offsets = new Set(
      Array.from({ length: 40 }, (_, index) => jitterOffset("monocyte-yes", index)),
    );
    expect(offsets.size).toBeGreaterThan(35);
  });
});
