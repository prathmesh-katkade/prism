import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: { baseURL: "http://127.0.0.1:3100", trace: "retain-on-failure" },
  webServer: { command: "npm run dev --workspace=@prism/web -- --port 3100", url: "http://127.0.0.1:3100", reuseExistingServer: !process.env.CI },
  projects: [{ name: "desktop-chromium", use: { ...devices["Desktop Chrome"] } }]
});
