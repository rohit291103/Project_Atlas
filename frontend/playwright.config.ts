import { defineConfig } from "@playwright/test";

/* The UI smoke suite runs against a *running* app, not a mocked one — the whole
 * reason it exists is that typecheck-and-build said "fine" while three real
 * defects sat in the rendered page. It needs two processes up:
 *
 *   uvicorn atlas.api.app:app --port 8000   (ATLAS_DEV_CORS=1, seeded database)
 *   npm run dev                              (this Vite server)
 *
 * `webServer` starts Vite; the API is deliberately not auto-started, because it
 * needs a database whose contents the assertions depend on.
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  // One worker, in order. These tests drive a *shared, mutable* event log, so
  // parallel workers would race each other's confirmations — the first version
  // of this suite failed exactly that way.
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL: "http://localhost:5173",
    viewport: { width: 1280, height: 900 },
    colorScheme: "dark", // the canonical surface (design baseline §2)
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
