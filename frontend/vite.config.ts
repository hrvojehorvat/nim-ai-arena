import { defineConfig } from "vite";

const BACKEND = "http://localhost:8000";

// Dev server proxies API + WebSocket calls to the FastAPI backend, so the browser
// talks to a single origin and no CORS setup is needed.
export default defineConfig({
  server: {
    proxy: {
      "/matches": BACKEND,
      "/agents": BACKEND,
      "/health": BACKEND,
      "/ws": { target: BACKEND, ws: true },
    },
  },
});
