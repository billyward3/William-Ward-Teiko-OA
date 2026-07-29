import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { PopulationComparison } from "../lib/types";
import { Boxplot } from "./Boxplot";

/**
 * Seven observations against four, so a chart that drew one group's points
 * twice, or drew only the first group, has a visibly wrong count. The two
 * groups also overlap in range but not in median, which is the case a box
 * summary alone would obscure and the plotted points exist to reveal.
 */
const COMPARISON: PopulationComparison = {
  population: "b_cell",
  n: { no: 7, yes: 4 },
  median: { no: 12.5, yes: 9 },
  values: {
    no: [10.5, 11.2, 12.1, 12.5, 13.4, 14.8, 21.6],
    yes: [8.1, 8.7, 9.3, 12.9],
  },
  p_value: 0.041,
  q_value: 0.102,
  shift: 3.2,
  shift_ci: [-0.4, 6.1],
  simultaneous_ci: [-1.9, 7.4],
  effect_size: 0.86,
};

function renderPlot() {
  return render(
    <Boxplot comparison={COMPARISON} groups={["no", "yes"]} splitOn="response" />,
  );
}

describe("Boxplot", () => {
  it("draws every observation, not just the summary", () => {
    // A boxplot is five numbers, and five numbers cannot say whether they came
    // from four observations or four hundred.
    const { container } = renderPlot();
    expect(container.querySelectorAll("circle.boxplot__point")).toHaveLength(11);
  });

  it("writes each group's size beside its box", () => {
    renderPlot();
    expect(screen.getByText("n = 7")).toBeInTheDocument();
    expect(screen.getByText("n = 4")).toBeInTheDocument();
  });

  it("names both groups under the axis", () => {
    const { container } = renderPlot();
    const labels = [...container.querySelectorAll("text.boxplot__group")].map(
      (node) => node.textContent,
    );
    expect(labels).toEqual(["no", "yes"]);
  });

  it("gives each group a box, a median and two whiskers", () => {
    const { container } = renderPlot();
    expect(container.querySelectorAll("rect.boxplot__rect")).toHaveLength(2);
    expect(container.querySelectorAll("line.boxplot__median")).toHaveLength(2);
    expect(container.querySelectorAll("line.boxplot__whisker")).toHaveLength(4);
  });

  it("colours the two medians differently, and by position", () => {
    const { container } = renderPlot();
    const medians = [...container.querySelectorAll("line.boxplot__median")].map(
      (node) => node.getAttribute("stroke"),
    );
    expect(medians[0]).not.toBe(medians[1]);
    expect(new Set(medians).size).toBe(2);
  });

  it("quotes the API's q-value and interval rather than recomputing them", () => {
    renderPlot();
    expect(screen.getByText(/q = 0\.102/)).toBeInTheDocument();
    expect(screen.getByText(/\[−0\.40, \+6\.10\] pp/)).toBeInTheDocument();
  });

  it("describes itself to a screen reader", () => {
    renderPlot();
    expect(
      screen.getByRole("img", { name: /b_cell relative frequency by response/ }),
    ).toBeInTheDocument();
  });

  it("puts each point at a stable, distinct horizontal offset", () => {
    // Jitter derived from a random number would move every point on re-render,
    // which turns a refetch of the same cohort into a different-looking chart.
    const first = renderPlot().container.innerHTML;
    const second = renderPlot().container.innerHTML;
    expect(first).toBe(second);
  });

  it("survives a group the cohort matched nothing in", () => {
    const empty: PopulationComparison = {
      ...COMPARISON,
      n: { no: 7, yes: 0 },
      values: { no: COMPARISON.values.no ?? [], yes: [] },
    };
    const { container } = render(
      <Boxplot comparison={empty} groups={["no", "yes"]} splitOn="response" />,
    );
    expect(container.querySelectorAll("rect.boxplot__rect")).toHaveLength(1);
    expect(screen.getByText("n = 0")).toBeInTheDocument();
  });
});
