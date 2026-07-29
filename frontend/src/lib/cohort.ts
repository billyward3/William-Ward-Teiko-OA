import type { CohortOut } from "./types";

/**
 * The cohort as the controls hold it, and how it becomes a query string.
 *
 * Two traps live here, and both are invisible in the shape of a response.
 *
 * **An omitted parameter is not "unconstrained".** Each endpoint defaults its
 * parameters to the cohort its Part of the spec asks about, so `/api/comparison`
 * with no `condition` means `condition=melanoma`, not "every condition". A panel
 * that dropped cleared fields from the query string would therefore find the
 * defaults unclearable and the wider cohorts unreachable. So every field is sent
 * on every request, and a cleared one is sent as an empty value, which the API
 * coerces back to unconstrained.
 *
 * **Filters are exact-match and case-sensitive.** `condition=Melanoma` is not a
 * near miss, it is an empty table with nothing to say why. Every value the panel
 * can produce therefore comes from `/api/filters`, never from typing.
 */
export interface CohortSelection {
  condition: string;
  treatment: string;
  response: string;
  sex: string;
  sample_type: string;
  /** Empty means cleared, which is every timepoint, not none of them. */
  timepoints: number[];
}

/** The single-valued fields, in the order the API and the panel present them. */
export const COHORT_FIELDS = [
  "condition",
  "treatment",
  "response",
  "sex",
  "sample_type",
] as const;

export type CohortField = (typeof COHORT_FIELDS)[number];

/** Human labels for the controls. Display only; nothing keys off these. */
export const FIELD_LABELS: Record<CohortField, string> = {
  condition: "Condition",
  treatment: "Treatment",
  response: "Response",
  sex: "Sex",
  sample_type: "Sample type",
};

export const EMPTY_SELECTION: CohortSelection = {
  condition: "",
  treatment: "",
  response: "",
  sex: "",
  sample_type: "",
  timepoints: [],
};

/** The API's `null`-for-unconstrained shape, as the `""`-for-cleared one. */
export function selectionFrom(cohort: CohortOut): CohortSelection {
  return {
    condition: cohort.condition ?? "",
    treatment: cohort.treatment ?? "",
    response: cohort.response ?? "",
    sex: cohort.sex ?? "",
    sample_type: cohort.sample_type ?? "",
    timepoints: cohort.timepoints ?? [],
  };
}

/**
 * The query parameters for a selection: every field, always.
 *
 * A cleared field is sent as an empty value rather than omitted, because
 * omitting it would re-apply the endpoint's default instead of widening the
 * cohort. The same holds for `timepoint`, which is repeated once per value and
 * sent once empty when there are none.
 */
export function cohortParams(selection: CohortSelection): URLSearchParams {
  const params = new URLSearchParams();
  for (const field of COHORT_FIELDS) {
    params.set(field, selection[field]);
  }
  if (selection.timepoints.length === 0) {
    params.append("timepoint", "");
  } else {
    for (const timepoint of selection.timepoints) {
      params.append("timepoint", String(timepoint));
    }
  }
  return params;
}

/** True when nothing is selected, so a caption can say the cohort is everything. */
export function isUnconstrained(selection: CohortSelection): boolean {
  return (
    COHORT_FIELDS.every((field) => selection[field] === "") &&
    selection.timepoints.length === 0
  );
}

/**
 * A one-line description of the cohort a response was computed over.
 *
 * Built from the echoed cohort rather than from the controls, so it describes
 * the numbers on screen and not the request in flight.
 */
export function describeCohort(cohort: CohortOut): string {
  const parts: string[] = [];
  for (const field of COHORT_FIELDS) {
    const value = cohort[field];
    if (value !== null) {
      parts.push(`${FIELD_LABELS[field].toLowerCase()} ${value}`);
    }
  }
  if (cohort.timepoints !== null && cohort.timepoints.length > 0) {
    const days = cohort.timepoints.join(", ");
    parts.push(`day ${days}`);
  }
  return parts.length > 0 ? parts.join(" · ") : "every sample";
}
