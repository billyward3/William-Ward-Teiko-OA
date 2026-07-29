import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ABSENT } from "../lib/format";
import type { Comparison, PopulationComparison } from "../lib/types";
import { StatisticsTable } from "./StatisticsTable";

/**
 * Three populations covering the three states a row can be in: significant,
 * tested but not significant, and too small to test.
 *
 * Group sizes are unequal, medians differ between groups and between
 * populations, and `simultaneous_alpha` is alpha over three rather than over
 * five, so the two interval columns cannot be confused for each other and a
 * hardcoded "99%" heading fails.
 */
const TESTED_SIGNIFICANT: PopulationComparison = {
  population: "b_cell",
  n: { no: 7, yes: 5 },
  median: { no: 12.5, yes: 8.25 },
  values: { no: [11, 12, 12.5, 13, 14, 15, 16], yes: [7, 8, 8.25, 9, 10] },
  p_value: 0.0004,
  q_value: 0.0012,
  shift: 4.1,
  shift_ci: [1.2, 6.9],
  simultaneous_ci: [0.4, 7.8],
  effect_size: 0.94,
};

const TESTED_NULL_RESULT: PopulationComparison = {
  population: "cd4_t_cell",
  n: { no: 7, yes: 5 },
  median: { no: 30.1, yes: 31.4 },
  values: { no: [29, 30, 30.1, 31, 32, 33, 34], yes: [30, 31, 31.4, 32, 33] },
  p_value: 0.62,
  q_value: 0.885,
  shift: -0.7,
  shift_ci: [-3.1, 1.6],
  simultaneous_ci: [-4.4, 2.9],
  effect_size: 0.41,
};

const NOT_TESTED: PopulationComparison = {
  population: "nk_cell",
  n: { no: 7, yes: 2 },
  median: { no: 4.4, yes: 4.6 },
  values: { no: [4, 4.2, 4.4, 4.5, 4.6, 4.8, 5], yes: [4.5, 4.7] },
  p_value: null,
  q_value: null,
  shift: null,
  shift_ci: null,
  simultaneous_ci: null,
  effect_size: null,
};

const COMPARISON: Comparison = {
  cohort: {
    condition: "melanoma",
    treatment: "miraclib",
    response: null,
    sex: null,
    sample_type: "PBMC",
    timepoints: [0],
  },
  split_on: "response",
  groups: ["no", "yes"],
  n_samples: { no: 7, yes: 5 },
  n_subjects: { no: 7, yes: 5 },
  repeated_measures: false,
  n_tested: 3,
  alpha: 0.05,
  simultaneous_alpha: 0.05 / 3,
  populations: [TESTED_SIGNIFICANT, TESTED_NULL_RESULT, NOT_TESTED],
};

/** The `<tr>` whose leading header cell names this population. */
function row(population: string): HTMLElement {
  const found = screen
    .getAllByRole("row")
    .find((candidate) =>
      candidate.querySelector("th")?.textContent?.startsWith(population),
    );
  if (found === undefined) {
    throw new Error(`no row found for ${population}`);
  }
  return found;
}

describe("StatisticsTable", () => {
  it("labels the per-group columns with the split column's own values", () => {
    render(<StatisticsTable comparison={COMPARISON} />);
    // Anchored, because an unanchored /n · no/ also matches "media(n · no)".
    expect(
      screen.getByRole("columnheader", { name: "n · no" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: "median · yes" }),
    ).toBeInTheDocument();
  });

  it("distinguishes the marginal interval from the family-wise one", () => {
    render(<StatisticsTable comparison={COMPARISON} />);
    expect(screen.getByRole("columnheader", { name: "95% CI" })).toBeInTheDocument();
    expect(
      screen.getByRole("columnheader", { name: /98\.3% CI, family-wise/ }),
    ).toBeInTheDocument();
  });

  it("shows every number for a tested population", () => {
    render(<StatisticsTable comparison={COMPARISON} />);
    const cells = within(row("b_cell")).getAllByRole("cell");
    expect(cells.map((cell) => cell.textContent)).toEqual([
      "7",
      "5",
      "12.50%",
      "8.25%",
      "+4.10",
      "[+1.20, +6.90]",
      "[+0.40, +7.80]",
      "< 0.001",
      "0.001",
      "0.940",
    ]);
  });

  it("leaves an untested population's statistics blank rather than zero", () => {
    render(<StatisticsTable comparison={COMPARISON} />);
    const cells = within(row("nk_cell")).getAllByRole("cell");
    // Counts and medians are still known; everything the test would have
    // produced is not.
    expect(cells.map((cell) => cell.textContent)).toEqual([
      "7",
      "2",
      "4.40%",
      "4.60%",
      ABSENT,
      ABSENT,
      ABSENT,
      ABSENT,
      ABSENT,
      ABSENT,
    ]);
  });

  it("marks significance in words, judged by q rather than by p", () => {
    render(<StatisticsTable comparison={COMPARISON} />);
    expect(within(row("b_cell")).getByText("significant")).toBeInTheDocument();
    expect(within(row("cd4_t_cell")).queryByText("significant")).toBeNull();
    expect(within(row("nk_cell")).getByText("not tested")).toBeInTheDocument();
  });

  it("does not call a result significant on a p-value alone", () => {
    // p = 0.02 clears alpha; q = 0.06 does not. Correction across the family is
    // what decides, and a table keyed off p would disagree with the figure.
    const borderline: Comparison = {
      ...COMPARISON,
      populations: [
        { ...TESTED_SIGNIFICANT, p_value: 0.02, q_value: 0.06 },
      ],
    };
    render(<StatisticsTable comparison={borderline} />);
    expect(screen.queryByText("significant")).toBeNull();
  });
});
