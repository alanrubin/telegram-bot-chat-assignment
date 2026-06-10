import { defineConfig } from "vite";
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
});
