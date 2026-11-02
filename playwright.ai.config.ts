import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/ai-e2e", workers: 1, retries: 0, forbidOnly: Boolean(process.env.CI),
  reporter: "list", use: { baseURL: "http://127.0.0.1:3200", trace: "off", reducedMotion: "reduce" },
  projects: [
    { name: "desktop-ai-contract", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
    { name: "mobile-ai-contract", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    { command: "uv run --directory backend --locked --no-sync python -B -m tests.fixtures.live_ai_e2e_server auth", url: "http://127.0.0.1:8101/health", reuseExistingServer: false, timeout: 60_000 },
    { command: "uv run --directory backend --locked --no-sync python -B -m tests.fixtures.live_ai_e2e_server backend", url: "http://127.0.0.1:8100/api/v1/health/ready", reuseExistingServer: false, timeout: 60_000 },
    {
      command: "npm run build && npm run start -- --hostname 127.0.0.1 --port 3200",
      url: "http://127.0.0.1:3200", reuseExistingServer: false, timeout: 180_000,
      env: {
        NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8100",
        NEXT_PUBLIC_SUPABASE_URL: "http://127.0.0.1:8101",
        NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "sb_publishable_controlled_test_fixture",
        NEXT_PUBLIC_SITE_URL: "http://127.0.0.1:3200", NEXT_PUBLIC_AI_MODE: "real",
      },
    },
  ],
});
