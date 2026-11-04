import { defineConfig, devices } from "@playwright/test";

// Custom lessons end to end with the backend's mock provider transport (never Gemini, no key).
export default defineConfig({
  testDir: "./tests/custom-lessons-e2e", workers: 1, retries: process.env.CI ? 1 : 0, forbidOnly: Boolean(process.env.CI),
  reporter: "list", use: { baseURL: "http://127.0.0.1:3300", trace: "off", reducedMotion: "reduce" },
  projects: [
    { name: "desktop-custom-lessons", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } } },
    { name: "mobile-custom-lessons", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    { command: "uv run --directory backend --locked --no-sync python -B -m tests.fixtures.custom_lessons_e2e_server auth", url: "http://127.0.0.1:8111/health", reuseExistingServer: false, timeout: 60_000 },
    { command: "uv run --directory backend --locked --no-sync python -B -m tests.fixtures.custom_lessons_e2e_server backend", url: "http://127.0.0.1:8110/api/v1/health/ready", reuseExistingServer: false, timeout: 60_000 },
    {
      command: "npm run build && npm run start -- --hostname 127.0.0.1 --port 3300",
      url: "http://127.0.0.1:3300", reuseExistingServer: false, timeout: 180_000,
      env: {
        NEXT_PUBLIC_API_BASE_URL: "http://127.0.0.1:8110",
        NEXT_PUBLIC_SUPABASE_URL: "http://127.0.0.1:8111",
        NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "sb_publishable_controlled_test_fixture",
        NEXT_PUBLIC_SITE_URL: "http://127.0.0.1:3300", NEXT_PUBLIC_AI_MODE: "real",
        // Test-only: the leaderboard has no backend endpoint yet, so this stack uses the labelled demo adapter.
        NEXT_PUBLIC_LEADERBOARD_DEMO: "1",
      },
    },
  ],
});
