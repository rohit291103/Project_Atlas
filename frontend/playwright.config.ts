import { defineConfig } from "@playwright/test";

/* The UI smoke suite runs against a *running* app, not a mocked one — the whole
 * reason it exists is that typecheck-and-build said "fine" while three real
 * defects sat in the rendered page. It needs two processes up:
 *
 *   ATLAS_DEV_CORS=1 uvicorn atlas.api.app:app --port 8000   (seeded database)
 *   npm run dev                                              (this Vite server)
 *
 * `webServer` starts Vite; the API is deliberately not auto-started, because it
 * needs a database whose contents the assertions depend on.
 *
 * **The port is configurable, and that is not a convenience.** `webServer` has
 * `reuseExistingServer`, so a Vite already running from another session is
 * adopted silently — including one started against a *different* API. That is
 * exactly what happened while slice 2B's screens were being checked: the suite
 * passed twelve tests against a stale API that did not have the endpoints the
 * new screen calls, and the only visible symptom was a "Not Found" banner in a
 * screenshot. Pointing both the base URL and the API at explicit ports makes a
 * second, isolated app trivial to stand up:
 *
 *   ATLAS_UI_PORT=5174 ATLAS_API_BASE=http://localhost:8011 npm run test:ui
 */
const UI_PORT = process.env.ATLAS_UI_PORT ?? "5173";
const BASE_URL = `http://localhost:${UI_PORT}`;

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  // One worker, in order. These tests drive a *shared, mutable* event log, so
  // parallel workers would race each other's confirmations — the first version
  // of this suite failed exactly that way.
  workers: 1,
  fullyParallel: false,
  use: {
    baseURL: BASE_URL,
    viewport: { width: 1280, height: 900 },
    colorScheme: "dark", // the canonical surface (design baseline §2)
  },
  webServer: {
    command: `npm run dev -- --port ${UI_PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: true,
    timeout: 60_000,
    env: process.env.ATLAS_API_BASE ? { VITE_API_BASE: process.env.ATLAS_API_BASE } : {},
  },
});
