import { describe, expect, it } from "vitest";
import {
  COHORT_FIELDS,
  cohortParams,
  describeCohort,
  EMPTY_SELECTION,
  isUnconstrained,
  selectionFrom,
  type CohortSelection,
} from "./cohort";
import type { CohortOut } from "./types";

/**
 * A selection with a different value in every set field and two fields cleared,
 * at the third and fifth positions.
 *
 * The shape is the point. Distinct values mean a transposition, writing one
 * field's value under another's name, fails rather than agreeing with itself;
 * two cleared fields in non-adjacent positions mean an off-by-one in the field
 * order fails; and clearing the middle one means "drop empty values" cannot be
 * mistaken for correct by a test that only clears the last.
 */
const MIXED: CohortSelection = {
  condition: "melanoma",
  treatment: "miraclib",
  response: "",
  sex: "M",
  sample_type: "",
  timepoints: [0, 14],
};

describe("cohortParams", () => {
  it("sends every field, in order, with cleared ones present but empty", () => {
    expect(cohortParams(MIXED).toString()).toBe(
      "condition=melanoma&treatment=miraclib&response=&sex=M&sample_type=" +
        "&timepoint=0&timepoint=14",
    );
  });

  it("sends a cleared field rather than omitting it", () => {
    // This is the whole reason the function exists. Each endpoint defaults its
    // parameters to the cohort its Part of the spec asks about, so an omitted
    // `condition` means `melanoma`, not "every condition". Dropping empties
    // would make the defaults unclearable.
    const params = cohortParams(EMPTY_SELECTION);
    for (const field of COHORT_FIELDS) {
      expect(params.has(field)).toBe(true);
      expect(params.get(field)).toBe("");
    }
  });

  it("sends one empty timepoint when none are ticked", () => {
    // Absent and blank differ for this parameter too: absent gets the
    // endpoint's default, blank clears it.
    expect(cohortParams(EMPTY_SELECTION).getAll("timepoint")).toEqual([""]);
  });

  it("repeats the timepoint parameter once per value, in the given order", () => {
    const params = cohortParams({ ...EMPTY_SELECTION, timepoints: [14, 0, 7] });
    expect(params.getAll("timepoint")).toEqual(["14", "0", "7"]);
  });

  it("escapes values instead of letting them alter the query string", () => {
    const params = cohortParams({ ...EMPTY_SELECTION, condition: "a&b=c d" });
    expect(params.toString()).toContain("condition=a%26b%3Dc+d");
    expect(params.get("condition")).toBe("a&b=c d");
    expect(params.get("treatment")).toBe("");
  });

  it("never emits a key the cohort does not have", () => {
    const keys = new Set(cohortParams(MIXED).keys());
    expect([...keys].sort()).toEqual(
      [...COHORT_FIELDS, "timepoint"].slice().sort(),
    );
  });
});

describe("selectionFrom", () => {
  it("reads the API's null-for-unconstrained as the panel's empty value", () => {
    const cohort: CohortOut = {
      condition: "melanoma",
      treatment: null,
      response: "yes",
      sex: "M",
      sample_type: null,
      timepoints: [0],
    };
    expect(selectionFrom(cohort)).toEqual({
      condition: "melanoma",
      treatment: "",
      response: "yes",
      sex: "M",
      sample_type: "",
      timepoints: [0],
    });
  });

  it("round-trips through the query string without acquiring a filter", () => {
    const everything: CohortOut = {
      condition: null,
      treatment: null,
      response: null,
      sex: null,
      sample_type: null,
      timepoints: null,
    };
    const params = cohortParams(selectionFrom(everything));
    expect(params.toString()).toBe(
      "condition=&treatment=&response=&sex=&sample_type=&timepoint=",
    );
  });
});

describe("isUnconstrained", () => {
  it("is true only when nothing at all is selected", () => {
    expect(isUnconstrained(EMPTY_SELECTION)).toBe(true);
    expect(isUnconstrained(MIXED)).toBe(false);
    expect(isUnconstrained({ ...EMPTY_SELECTION, timepoints: [0] })).toBe(false);
    expect(isUnconstrained({ ...EMPTY_SELECTION, sex: "F" })).toBe(false);
  });
});

describe("describeCohort", () => {
  it("names only the constrained fields", () => {
    expect(
      describeCohort({
        condition: "melanoma",
        treatment: "miraclib",
        response: null,
        sex: null,
        sample_type: "PBMC",
        timepoints: [0],
      }),
    ).toBe("condition melanoma · treatment miraclib · sample type PBMC · day 0");
  });

  it("says so when the cohort constrains nothing", () => {
    expect(
      describeCohort({
        condition: null,
        treatment: null,
        response: null,
        sex: null,
        sample_type: null,
        timepoints: null,
      }),
    ).toBe("every sample");
  });

  it("lists several timepoints", () => {
    expect(
      describeCohort({
        condition: null,
        treatment: null,
        response: null,
        sex: null,
        sample_type: null,
        timepoints: [0, 7, 14],
      }),
    ).toBe("day 0, 7, 14");
  });
});
