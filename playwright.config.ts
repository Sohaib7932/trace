import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  // One fixture clock is shared by the test server; serialize controlled-time journeys.
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3100",
    reducedMotion: "reduce",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop-chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile-chromium", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [{
    command: "uv run --directory backend --locked --no-sync python -B -m scripts.auth_fixture",
    url: "http://127.0.0.1:8001/health",
    reuseExistingServer: false,
    timeout: 60_000,
  }, {
    command: "uv run --directory backend --locked --no-sync python -B -m tests.fixtures.phase0_e2e_server",
    env: { TRACE_E2E_CLOCK_FILE: resolve("test-results/e2e-clock.json") },
    url: "http://127.0.0.1:8000/api/v1/health/ready",
    reuseExistingServer: false,
    timeout: 60_000,
  }, {
    command: "npm run start -- --hostname 127.0.0.1 --port 3100",
    url: "http://127.0.0.1:3100",
    reuseExistingServer: false,
    timeout: 60_000,
  }],
});
