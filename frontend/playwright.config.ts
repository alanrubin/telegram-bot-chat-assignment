import { defineConfig, devices } from "@playwright/test";

// E2E smoke tests. The WebSocket is mocked in-browser (page.routeWebSocket), so these run
// against the Vite dev server alone — no backend and no Telegram required.
export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://localhost:5173" },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
