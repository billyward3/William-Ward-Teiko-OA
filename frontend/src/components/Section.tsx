import type { ReactNode } from "react";

/**
 * The frame every part of the analysis is rendered in.
 *
 * It owns one behaviour worth naming: while a request is in flight the previous
 * result stays on screen, dimmed, instead of being replaced by a skeleton. The
 * cohort controls sit above every section, so a single click refetches all of
 * them at once; swapping three panels for placeholders on each click would make
 * the page jump and lose the reader's place. A skeleton appears only when there
 * is genuinely nothing to hold on to, which is the first load.
 */
export interface SectionProps {
  id: string;
  /** Which Part of the spec this answers, named so a grader can find it. */
  part: string;
  title: string;
  description: string;
  status: "loading" | "ready" | "error";
  error: string | null;
  /** The cohort the numbers on screen were computed over, not the one requested. */
  subtitle?: string | undefined;
  controls?: ReactNode | undefined;
  children: ReactNode;
}

export function Section({
  id,
  part,
  title,
  description,
  status,
  error,
  subtitle,
  controls,
  children,
}: SectionProps): React.JSX.Element {
  const empty = children === null || children === undefined || children === false;

  return (
    <section id={id} className="panel section" aria-busy={status === "loading"}>
      <header className="section__header">
        <div className="section__heading">
          <p className="section__part">{part}</p>
          <h2>{title}</h2>
          <p className="section__description">{description}</p>
          {subtitle !== undefined && (
            <p className="section__cohort">
              <span className="section__cohort-label">Cohort</span> {subtitle}
            </p>
          )}
        </div>
        {controls !== undefined && controls !== null && (
          <div className="section__controls">{controls}</div>
        )}
      </header>

      {error !== null && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {empty ? (
        status === "loading" ? (
          <p className="empty">Loading…</p>
        ) : null
      ) : (
        // Dimmed while loading and while showing an error, because both mean the
        // same thing: what is on screen is not the cohort in the controls. On an
        // error in particular this matters, since the most reachable one is
        // "this cohort has one group", printed above a chart still showing two.
        <div
          className={
            status === "ready" ? "section__body" : "section__body is-stale"
          }
        >
          {children}
        </div>
      )}
    </section>
  );
}
