import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const python = process.env.PRISM_PYTHON ?? (process.platform === "win32" ? path.resolve(".venv/Scripts/python.exe") : "python");
const apiDirectory = path.resolve("apps/api/src");

export default defineConfig({
  testDir: "./e2e-live",
  timeout: 45_000,
  // Live-e2e specs share one real FastAPI backend and its single global
  // "active dataset" pointer (overview_store.latest()) by design - that is
  // what makes them "live" rather than mocked. Running spec files across
  // parallel workers races concurrent dataset uploads against that shared
  // pointer, so a worker's own just-uploaded dataset can lose "latest" to
  // another worker's upload before its page finishes loading. Durable,
  // DB-backed persistence (Phase 9) widened that race window enough to
  // make it flake reliably, so these tests always run single-worker.
  workers: 1,
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
