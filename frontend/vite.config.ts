/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/** Where `npm run dev` forwards `/api` while the built app is served by FastAPI.
 *
 * Only the dev server uses this. The production bundle calls `/api/...` on
 * whatever origin served it, which is what makes the Codespaces forwarded
 * `https://<name>-8000.app.github.dev` work without a CORS or mixed-content
 * exception. Nothing in `src/` may name a host.
 */
const API_ORIGIN = process.env.CELLCOUNT_API_ORIGIN ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  // Relative asset URLs, so the bundle does not assume it is mounted at the
  // root of its origin.
  base: "./",
  build: {
    outDir: "dist",
    // The API refuses to guess: a stale bundle served next to a fresh one is
    // worse than a slow first load.
    emptyOutDir: true,
    sourcemap: true,
  },
  server: {
    proxy: {
      "/api": {
        target: API_ORIGIN,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    restoreMocks: true,
  },
});
