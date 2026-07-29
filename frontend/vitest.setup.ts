import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Testing Library registers its own cleanup only when Vitest's globals are on.
// They are not, so without this every render in a file accumulates in the same
// document and queries start matching elements from earlier tests.
afterEach(cleanup);
