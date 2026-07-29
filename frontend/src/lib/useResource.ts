import { useEffect, useState } from "react";
import { ApiError } from "./api";

/**
 * One request's state, with the previous result kept while the next is in flight.
 *
 * Dropping back to a spinner on every filter change would make the page jump on
 * each click, and the unfiltered comparison takes seconds because it materialises
 * every pairwise difference to invert the rank test. Holding the last render,
 * dimmed, keeps the layout still and keeps the reader oriented. `data` is
 * therefore the *last successful* result, which may be older than `status`.
 */
export interface Resource<T> {
  status: "loading" | "ready" | "error";
  data: T | null;
  error: string | null;
}

const INITIAL: Resource<never> = { status: "loading", data: null, error: null };

function describe(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

/**
 * Run `load` whenever its identity changes, cancelling the request it replaces.
 *
 * `load` must be memoised by the caller, since it is the dependency. The
 * `AbortSignal` is not a nicety: filter changes arrive faster than the server
 * answers, and without cancellation a slow reply to a stale cohort can land
 * after a fast reply to the current one and overwrite it. The signal is checked
 * again after settling because an abort raised between the response and the
 * state update would otherwise slip through.
 */
export function useResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
): Resource<T> {
  const [state, setState] = useState<Resource<T>>(INITIAL);

  useEffect(() => {
    const controller = new AbortController();
    setState((previous) => ({
      status: "loading",
      data: previous.data,
      error: null,
    }));

    load(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) {
          setState({ status: "ready", data, error: null });
        }
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setState((previous) => ({
            status: "error",
            data: previous.data,
            error: describe(error),
          }));
        }
      },
    );

    return () => {
      controller.abort();
    };
  }, [load]);

  return state;
}
