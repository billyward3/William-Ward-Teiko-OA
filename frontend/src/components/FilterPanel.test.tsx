import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  cohortParams,
  EMPTY_SELECTION,
  type CohortSelection,
} from "../lib/cohort";
import type { FilterOptions } from "../lib/types";
import { FilterPanel } from "./FilterPanel";

/**
 * Option lists of deliberately different lengths, with values that do not look
 * alike across fields.
 *
 * If every field offered the same two values, a panel that wired the wrong
 * `onChange` to the wrong `<select>` would still produce a plausible-looking
 * selection. Here it cannot: `PBMC` can only have come from sample type.
 * Timepoints are listed out of order to pin that the panel, not the API,
 * decides the order it sends them in.
 */
const OPTIONS: FilterOptions = {
  fields: {
    condition: ["carcinoma", "healthy", "melanoma"],
    treatment: ["miraclib", "none", "phauximab"],
    response: ["no", "yes"],
    sex: ["F", "M"],
    sample_type: ["PBMC", "WB"],
  },
  timepoints: [0, 7, 14],
  populations: ["b_cell", "cd4_t_cell", "cd8_t_cell", "monocyte", "nk_cell"],
  split_columns: ["condition", "response", "sample_type", "sex", "treatment"],
  default_cohort: {
    condition: "melanoma",
    treatment: "miraclib",
    response: null,
    sex: null,
    sample_type: "PBMC",
    timepoints: [0],
  },
};

const SPEC_COHORT: CohortSelection = {
  condition: "melanoma",
  treatment: "miraclib",
  response: "",
  sex: "",
  sample_type: "PBMC",
  timepoints: [0],
};

function renderPanel(selection: CohortSelection = SPEC_COHORT) {
  const onChange = vi.fn<(next: CohortSelection) => void>();
  render(
    <FilterPanel
      options={OPTIONS}
      selection={selection}
      onChange={onChange}
      specCohort={SPEC_COHORT}
      busy={false}
    />,
  );
  return { onChange, user: userEvent.setup() };
}

describe("FilterPanel controls", () => {
  it("offers only values the database actually contains", () => {
    renderPanel();
    const condition = screen.getByLabelText("Condition");
    const offered = [...condition.querySelectorAll("option")].map(
      (option) => option.value,
    );
    // The empty option is the cleared state, not a value.
    expect(offered).toEqual(["", "carcinoma", "healthy", "melanoma"]);
  });

  it("gives no way to type a value", () => {
    // Filters are exact-match and case-sensitive on the server, so `Melanoma`
    // would return an empty table with nothing to say why.
    const { container } = render(
      <FilterPanel
        options={OPTIONS}
        selection={SPEC_COHORT}
        onChange={vi.fn()}
        specCohort={SPEC_COHORT}
        busy={false}
      />,
    );
    const typeable = [...container.querySelectorAll("input")].filter(
      (input) => input.type !== "checkbox",
    );
    expect(typeable).toHaveLength(0);
  });

  it("shows the current selection in each control", () => {
    renderPanel();
    expect(screen.getByLabelText("Condition")).toHaveValue("melanoma");
    expect(screen.getByLabelText("Treatment")).toHaveValue("miraclib");
    expect(screen.getByLabelText("Sample type")).toHaveValue("PBMC");
    // Unconstrained fields sit on the empty option, not on their first value.
    expect(screen.getByLabelText("Response")).toHaveValue("");
    expect(screen.getByLabelText("Sex")).toHaveValue("");
  });
});

describe("FilterPanel state handling", () => {
  it("changes one field and leaves the rest exactly as they were", async () => {
    const { onChange, user } = renderPanel();
    await user.selectOptions(screen.getByLabelText("Sex"), "F");
    expect(onChange).toHaveBeenCalledWith({ ...SPEC_COHORT, sex: "F" });
  });

  it("clears a field to the empty value rather than dropping it", async () => {
    // The empty value is what the client sends and what the API reads as
    // unconstrained. A panel that deleted the key instead would re-apply the
    // endpoint's default cohort.
    const { onChange, user } = renderPanel();
    await user.selectOptions(screen.getByLabelText("Condition"), "");

    const next = onChange.mock.calls[0]?.[0];
    expect(next).toEqual({ ...SPEC_COHORT, condition: "" });
    expect(cohortParams(next as CohortSelection).get("condition")).toBe("");
  });

  it("clearing one field does not disturb another", async () => {
    const { onChange, user } = renderPanel();
    await user.selectOptions(screen.getByLabelText("Treatment"), "");
    const next = onChange.mock.calls[0]?.[0];
    expect(next?.condition).toBe("melanoma");
    expect(next?.sample_type).toBe("PBMC");
    expect(next?.timepoints).toEqual([0]);
  });

  it("adds a ticked timepoint in numeric order, not click order", async () => {
    const { onChange, user } = renderPanel();
    await user.click(screen.getByLabelText("day 14"));
    expect(onChange).toHaveBeenCalledWith({ ...SPEC_COHORT, timepoints: [0, 14] });
  });

  it("removes an unticked timepoint and leaves its neighbours", async () => {
    const { onChange, user } = renderPanel({
      ...SPEC_COHORT,
      timepoints: [0, 7, 14],
    });
    await user.click(screen.getByLabelText("day 7"));
    expect(onChange).toHaveBeenCalledWith({
      ...SPEC_COHORT,
      timepoints: [0, 14],
    });
  });

  it("says that no ticked day means every day, because empty is ambiguous", () => {
    renderPanel({ ...SPEC_COHORT, timepoints: [] });
    expect(
      screen.getByText(/None ticked: every timepoint, pooled\./),
    ).toBeInTheDocument();
  });

  it("clears every filter at once, including the timepoints", async () => {
    const { onChange, user } = renderPanel();
    await user.click(screen.getByRole("button", { name: /clear all filters/i }));
    expect(onChange).toHaveBeenCalledWith(EMPTY_SELECTION);
  });

  it("resets to the spec cohort from anywhere", async () => {
    const { onChange, user } = renderPanel(EMPTY_SELECTION);
    await user.click(
      screen.getByRole("button", { name: /reset to the spec cohort/i }),
    );
    expect(onChange).toHaveBeenCalledWith(SPEC_COHORT);
  });

  it("does not change anything on its own", async () => {
    // The panel is controlled: it reports intent and re-renders from the
    // selection it is handed, so a stale render cannot outlive a rejected change.
    const { onChange, user } = renderPanel();
    await user.selectOptions(screen.getByLabelText("Sex"), "M");
    expect(screen.getByLabelText("Sex")).toHaveValue("");
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});

describe("FilterPanel status", () => {
  it("says when the analysis is being recomputed", () => {
    render(
      <FilterPanel
        options={OPTIONS}
        selection={SPEC_COHORT}
        onChange={vi.fn()}
        specCohort={SPEC_COHORT}
        busy
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Recomputing");
  });
});
