import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Comparison } from "../lib/types";
import { IndependenceNote } from "./IndependenceNote";

/**
 * The groups are deliberately unequal, and the sample and subject totals are
 * different numbers that are not multiples of one another across groups.
 *
 * With 21 and 15 samples from 7 and 5 subjects, a component that summed the
 * wrong map prints 12 where it should print 36, and one that reported a single
 * group's count prints 21. Equal groups, or a fixture where samples happened to
 * equal subjects, would let both mistakes through.
 */
function comparison(overrides: Partial<Comparison> = {}): Comparison {
  return {
    cohort: {
      condition: "melanoma",
      treatment: "miraclib",
      response: null,
      sex: null,
      sample_type: "PBMC",
      timepoints: null,
    },
    split_on: "response",
    groups: ["no", "yes"],
    n_samples: { no: 21, yes: 15 },
    n_subjects: { no: 7, yes: 5 },
    repeated_measures: true,
    n_tested: 5,
    alpha: 0.05,
    simultaneous_alpha: 0.01,
    populations: [],
    ...overrides,
  };
}

describe("IndependenceNote", () => {
  it("warns, with both totals, when a subject contributed more than one sample", () => {
    render(<IndependenceNote comparison={comparison()} />);
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent(/not independent/i);
    expect(note).toHaveTextContent("36 samples");
    expect(note).toHaveTextContent("12 subjects");
  });

  it("says the p-values are optimistic, and how to fix it", () => {
    render(<IndependenceNote comparison={comparison()} />);
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent(/optimistic/i);
    expect(note).toHaveTextContent(/single day/i);
  });

  it("reports independence when each subject contributed one sample", () => {
    render(
      <IndependenceNote
        comparison={comparison({
          n_samples: { no: 7, yes: 5 },
          repeated_measures: false,
        })}
      />,
    );
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent(/are independent/i);
    expect(note).toHaveTextContent("12 samples");
    expect(note).not.toHaveTextContent(/optimistic/i);
  });

  it("trusts the server's flag rather than comparing the counts itself", () => {
    // The flag is the analysis's own conclusion. A component that recomputed it
    // from the two maps would quietly downgrade this warning to reassurance the
    // moment the two definitions drifted apart, which is exactly the failure
    // this caveat exists to prevent.
    render(
      <IndependenceNote
        comparison={comparison({
          n_samples: { no: 7, yes: 5 },
          n_subjects: { no: 7, yes: 5 },
          repeated_measures: true,
        })}
      />,
    );
    expect(screen.getByRole("note")).toHaveTextContent(/not independent/i);
  });

  it("says nothing at all when the cohort matched no subjects", () => {
    const { container } = render(
      <IndependenceNote
        comparison={comparison({
          groups: [],
          n_samples: {},
          n_subjects: {},
          repeated_measures: false,
        })}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
