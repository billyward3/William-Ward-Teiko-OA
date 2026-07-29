import {
  COHORT_FIELDS,
  EMPTY_SELECTION,
  FIELD_LABELS,
  type CohortField,
  type CohortSelection,
} from "../lib/cohort";
import type { FilterOptions } from "../lib/types";

/**
 * The one control surface for the whole page.
 *
 * Every section below re-renders against the same cohort, so the filters live
 * once, above everything they scope, rather than once per card.
 *
 * No control here accepts typing. Cohort filters are exact-match and
 * case-sensitive on the server, so `Melanoma` returns an empty table with
 * nothing to say why; every option offered is a value `/api/filters` read out of
 * the database. Clearing a control selects the empty value, which the client
 * sends as an empty parameter and the API reads as unconstrained.
 */
export interface FilterPanelProps {
  options: FilterOptions;
  selection: CohortSelection;
  onChange: (selection: CohortSelection) => void;
  /** The cohort Parts 3 and 4 are specified over, which is where the page opens. */
  specCohort: CohortSelection;
  busy: boolean;
}

export function FilterPanel({
  options,
  selection,
  onChange,
  specCohort,
  busy,
}: FilterPanelProps): React.JSX.Element {
  function setField(field: CohortField, value: string): void {
    onChange({ ...selection, [field]: value });
  }

  function toggleTimepoint(day: number, checked: boolean): void {
    const next = checked
      ? [...selection.timepoints, day].sort((a, b) => a - b)
      : selection.timepoints.filter((existing) => existing !== day);
    onChange({ ...selection, timepoints: next });
  }

  return (
    <section className="panel filters" aria-label="Cohort filters">
      <div className="filters__controls">
        {COHORT_FIELDS.map((field) => {
          const values = options.fields[field] ?? [];
          return (
            <div className="field" key={field}>
              <label htmlFor={`filter-${field}`}>{FIELD_LABELS[field]}</label>
              <select
                id={`filter-${field}`}
                value={selection[field]}
                onChange={(event) => {
                  setField(field, event.target.value);
                }}
              >
                <option value="">
                  Any {FIELD_LABELS[field].toLowerCase()}
                </option>
                {values.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </div>
          );
        })}

        <fieldset className="field field--timepoints">
          <legend>Days from treatment start</legend>
          <div className="checkboxes">
            {options.timepoints.map((day) => (
              <label className="checkbox" key={day}>
                <input
                  type="checkbox"
                  checked={selection.timepoints.includes(day)}
                  onChange={(event) => {
                    toggleTimepoint(day, event.target.checked);
                  }}
                />
                <span>day {day}</span>
              </label>
            ))}
          </div>
          <p className="field__hint">
            {selection.timepoints.length === 0
              ? "None ticked: every timepoint, pooled."
              : "Ticked days only."}
          </p>
        </fieldset>
      </div>

      <div className="filters__actions">
        <button
          type="button"
          onClick={() => {
            onChange(specCohort);
          }}
        >
          Reset to the spec cohort
        </button>
        <button
          type="button"
          onClick={() => {
            onChange(EMPTY_SELECTION);
          }}
        >
          Clear all filters
        </button>
        <span className="filters__status" role="status">
          {busy ? "Recomputing…" : ""}
        </span>
      </div>
    </section>
  );
}
