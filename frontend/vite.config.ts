import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API runs as a separate process (`uv run uvicorn atlas.api.app:app`) and
// allows this origin when ATLAS_DEV_CORS=1. In production the built assets are
// served from the API's own origin, so no proxy or CORS entry exists there.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
