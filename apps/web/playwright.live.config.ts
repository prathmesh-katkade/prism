import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const python = process.platform === "win32" ? path.resolve(".venv/Scripts/python.exe") : "python";
const apiDirectory = path.resolve("apps/api/src");

export default defineConfig({
  testDir: "./e2e-live",
  timeout: 45_000,
  use: { baseURL: "http://127.0.0.1:3100", trace: "retain-on-failure" },
  webServer: [
    {
      command: `"${python}" -m uvicorn --app-dir "${apiDirectory}" prism_api.main:app --host 127.0.0.1 --port 8000`,
      url: "http://127.0.0.1:8000/api/v1/platform/health",
      reuseExistingServer: false,
      env: { PRISM_ALLOWED_ORIGINS: '["http://127.0.0.1:3100"]' }
    },
    {
      command: "npm run dev --workspace=@prism/web -- --port 3100",
      url: "http://127.0.0.1:3100",
      reuseExistingServer: false
    }
  ],
  projects: [{ name: "live-chromium", use: { ...devices["Desktop Chrome"] } }]
});
