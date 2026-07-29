import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { Comparison, FilterOptions, Subsets, SummaryPage } from "./lib/types";

/**
 * The whole page against a stubbed API.
 *
 * The unit tests around it check each piece in isolation; this one checks that
 * the pieces are wired to the right endpoints, that a filter change reaches the
 * server as a new request, and that the independence warning survives the trip
 * from the response to the screen. Those are the failures that would leave every
 * component test green and the dashboard wrong.
 *
 * The fixture answers `/api/subsets` with numbers that appear nowhere else, so a
 * section rendered from the wrong response is visible rather than plausible.
 */
const FILTERS: FilterOptions = {
  fields: {
    condition: ["carcinoma", "healthy", "melanoma"],
    treatment: ["miraclib", "none", "phauximab"],
    response: ["no", "yes"],
    sex: ["F", "M"],
    sample_type: ["PBMC", "WB"],
  },
  timepoints: [0, 7, 14],
  populations: ["b_cell", "nk_cell"],
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

const SUMMARY: SummaryPage = {
  cohort: FILTERS.default_cohort,
  rows: [
    {
      sample: "s1",
      total_count: 41000,
      population: "b_cell",
      count: 4100,
      percentage: 10,
    },
    {
      sample: "s1",
      total_count: 41000,
      population: "nk_cell",
      count: 8200,
      percentage: 20,
    },
  ],
  total: 1312,
  limit: 100,
  offset: 0,
};

const COMPARISON: Comparison = {
  cohort: FILTERS.default_cohort,
  split_on: "response",
  groups: ["no", "yes"],
  // Three samples per subject: the cohort pools timepoints, so the warning fires.
  n_samples: { no: 21, yes: 15 },
  n_subjects: { no: 7, yes: 5 },
  repeated_measures: true,
  n_tested: 2,
  alpha: 0.05,
  simultaneous_alpha: 0.025,
  populations: [
    {
      population: "b_cell",
      n: { no: 21, yes: 15 },
      median: { no: 10.4, yes: 9.1 },
      values: { no: [9, 10.4, 12], yes: [8, 9.1, 10] },
      p_value: 0.31,
      q_value: 0.62,
      shift: 1.1,
      shift_ci: [-0.9, 3.2],
      simultaneous_ci: [-1.4, 3.8],
      effect_size: 0.58,
    },
  ],
};

const SUBSETS: Subsets = {
  cohort: FILTERS.default_cohort,
  samples_per_project: { prj1: 384, prj2: 0, prj3: 272 },
  subjects_per_response: { no: 325, yes: 331 },
  subjects_per_sex: { F: 312, M: 344 },
};

function stubApi(): string[] {
  const requested: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      requested.push(url);
      const body = url.startsWith("/api/filters")
        ? FILTERS
        : url.startsWith("/api/summary")
          ? SUMMARY
          : url.startsWith("/api/comparison")
            ? COMPARISON
            : SUBSETS;
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
      } as Response);
    }),
  );
  return requested;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("opens on the cohort the spec specifies, not on an empty one", async () => {
    const requested = stubApi();
    render(<App />);

    // Wait for the request this test is about, not for a different section's
    // heading. The comparison is issued only once /api/filters resolves and
    // supplies the default cohort; the subsets request does not wait on that.
    // Keying off Part 4's heading therefore let Part 3's request still be in
    // flight, and `find` returned undefined. Observed failing once in ten runs
    // before this change.
    await waitFor(() => {
      expect(requested.some((url) => url.startsWith("/api/comparison"))).toBe(
        true,
      );
    });

    const comparisonRequest = requested.find((url) =>
      url.startsWith("/api/comparison"),
    );
    expect(comparisonRequest).toContain("condition=melanoma");
    expect(comparisonRequest).toContain("treatment=miraclib");
    expect(comparisonRequest).toContain("sample_type=PBMC");
    expect(comparisonRequest).toContain("timepoint=0");
  });

  it("renders all three Parts from their own endpoints", async () => {
    stubApi();
    render(<App />);

    // Part 2's total, Part 3's populations, Part 4's project counts. None of
    // these numbers appears in more than one of the three fixtures.
    expect(await screen.findByText(/of 1,312/)).toBeInTheDocument();
    expect(
      await screen.findByRole("img", { name: /b_cell relative frequency/ }),
    ).toBeInTheDocument();
    expect(await screen.findByText("384")).toBeInTheDocument();
  });

  it("surfaces the independence warning where a reader cannot miss it", async () => {
    stubApi();
    render(<App />);

    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent(/not independent/i);
    expect(note).toHaveTextContent("36 samples");
    expect(note).toHaveTextContent("12 subjects");
  });

  it("reports a project the cohort matched nothing in, rather than dropping it", async () => {
    stubApi();
    render(<App />);

    // Awaited on the table rather than on the section heading: the heading is
    // rendered while the request is still in flight, so waiting for it would
    // assert against an empty section.
    const projects = await screen.findByRole("table", {
      name: /samples per project/i,
    });
    expect(within(projects).getByText("prj2")).toBeInTheDocument();
    expect(within(projects).getByText("0")).toBeInTheDocument();
  });

  it("re-requests every section when the cohort changes", async () => {
    const requested = stubApi();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByLabelText("Sex");

    const before = requested.length;
    await user.selectOptions(screen.getByLabelText("Sex"), "F");

    await waitFor(() => {
      expect(requested.length).toBeGreaterThan(before);
    });
    const after = requested.slice(before);
    expect(after.filter((url) => url.startsWith("/api/summary")).length).toBe(1);
    expect(after.filter((url) => url.startsWith("/api/comparison")).length).toBe(1);
    expect(after.filter((url) => url.startsWith("/api/subsets")).length).toBe(1);
    for (const url of after) {
      expect(url).toContain("sex=F");
    }
    // The options are read once; they cannot change while the page is open.
    expect(after.filter((url) => url.startsWith("/api/filters"))).toEqual([]);
  });

  it("sends the cleared value when a filter is emptied", async () => {
    const requested = stubApi();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByLabelText("Condition");

    const before = requested.length;
    await user.selectOptions(screen.getByLabelText("Condition"), "");

    await waitFor(() => {
      expect(requested.length).toBeGreaterThan(before);
    });
    for (const url of requested.slice(before)) {
      // Present and empty. Omitted would re-apply the endpoint's own default.
      expect(url).toContain("condition=&");
    }
  });

  it("explains itself when the API cannot be reached at all", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          status: 503,
          json: () =>
            Promise.resolve({ detail: "no database; run `make pipeline` first" }),
        } as Response),
      ),
    );
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/make pipeline/);
  });
});
