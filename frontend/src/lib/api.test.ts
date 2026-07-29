import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  fetchComparison,
  fetchFilters,
  fetchSubsets,
  fetchSummary,
} from "./api";
import { EMPTY_SELECTION, type CohortSelection } from "./cohort";

const SELECTION: CohortSelection = {
  condition: "melanoma",
  treatment: "miraclib",
  response: "",
  sex: "",
  sample_type: "PBMC",
  timepoints: [0],
};

/** Capture the URL a call requests, and answer with `body`. */
function stubFetch(body: unknown, init: { status?: number } = {}): () => string {
  const status = init.status ?? 200;
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      calls.push(String(input));
      return Promise.resolve({
        ok: status >= 200 && status < 300,
        status,
        json: () => Promise.resolve(body),
      } as Response);
    }),
  );
  return () => calls[0] ?? "";
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const signal = (): AbortSignal => new AbortController().signal;

describe("request URLs", () => {
  it("never names a host, so the forwarded Codespaces origin works", async () => {
    // A hardcoded http://localhost:8000 breaks under
    // https://<name>-8000.app.github.dev twice over: as mixed content, and as a
    // cross-origin request the server sends no CORS headers for.
    const urlOf = stubFetch({});
    await Promise.all([
      fetchFilters(signal()),
      fetchSummary(SELECTION, { limit: 10, offset: 0 }, signal()),
      fetchComparison(SELECTION, { splitOn: "response", alpha: 0.05 }, signal()),
      fetchSubsets(SELECTION, signal()),
    ]);
    const fetchMock = vi.mocked(globalThis.fetch);
    expect(fetchMock).toHaveBeenCalledTimes(4);
    for (const call of fetchMock.mock.calls) {
      const url = String(call[0]);
      expect(url.startsWith("/api/")).toBe(true);
      expect(url).not.toContain("://");
    }
    expect(urlOf()).toBe("/api/filters");
  });

  it("carries the cohort and the page on the summary request", async () => {
    const urlOf = stubFetch({});
    await fetchSummary(SELECTION, { limit: 250, offset: 500 }, signal());
    expect(urlOf()).toBe(
      "/api/summary?condition=melanoma&treatment=miraclib&response=&sex=" +
        "&sample_type=PBMC&timepoint=0&limit=250&offset=500",
    );
  });

  it("carries the split column and alpha on the comparison request", async () => {
    const urlOf = stubFetch({});
    await fetchComparison(
      EMPTY_SELECTION,
      { splitOn: "sex", alpha: 0.01 },
      signal(),
    );
    expect(urlOf()).toBe(
      "/api/comparison?condition=&treatment=&response=&sex=&sample_type=" +
        "&timepoint=&split_on=sex&alpha=0.01",
    );
  });

  it("sends the cleared cohort on the subsets request too", async () => {
    const urlOf = stubFetch({});
    await fetchSubsets(EMPTY_SELECTION, signal());
    expect(urlOf()).toBe(
      "/api/subsets?condition=&treatment=&response=&sex=&sample_type=&timepoint=",
    );
  });
});

describe("error reporting", () => {
  it("surfaces the server's own explanation of a bad request", async () => {
    // Selecting response = yes and splitting on response is an ordinary click,
    // and the API answers 400 with a sentence worth showing the user.
    stubFetch(
      { detail: "cohort split on 'response' has 1 group, expected two groups" },
      { status: 400 },
    );
    await expect(
      fetchComparison(SELECTION, { splitOn: "response", alpha: 0.05 }, signal()),
    ).rejects.toThrow(/expected two groups/);
  });

  it("carries the status alongside the message", async () => {
    stubFetch({ detail: "no database; run `make pipeline` first" }, { status: 503 });
    const error = await fetchSubsets(SELECTION, signal()).catch(
      (thrown: unknown) => thrown,
    );
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(503);
  });

  it("flattens FastAPI's validation detail instead of printing [object Object]", async () => {
    stubFetch(
      {
        detail: [
          { loc: ["query", "limit"], msg: "Input should be less than or equal to 1000" },
        ],
      },
      { status: 422 },
    );
    await expect(
      fetchSummary(SELECTION, { limit: 5000, offset: 0 }, signal()),
    ).rejects.toThrow("query.limit: Input should be less than or equal to 1000");
  });

  it("still explains itself when the error body is not JSON at all", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          status: 502,
          json: () => Promise.reject(new Error("Unexpected token <")),
        } as unknown as Response),
      ),
    );
    await expect(fetchFilters(signal())).rejects.toThrow(/status 502/);
  });
});
