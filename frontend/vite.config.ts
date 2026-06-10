import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// In dev the frontend (5173) and backend (8000) are separate origins, so proxy the
// same-origin "/ws" path to the backend. This keeps the client code identical in dev and
// production (where nginx proxies "/ws"), so the WebSocket URL is always relative.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./vitest.setup.ts",
    // Vitest runs unit/component tests under src/; Playwright e2e specs live in e2e/.
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
  },
});
