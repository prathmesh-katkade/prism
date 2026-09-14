import { defineConfig, devices } from "@playwright/test";
import path from "node:path";

const python = process.env.PRISM_PYTHON ?? (process.platform === "win32" ? path.resolve(".venv/Scripts/python.exe") : "python");
const apiDirectory = path.resolve("apps/api/src");
const externalBaseUrl = process.env.PRISM_LIVE_E2E_BASE_URL;
const localPythonPath = [
  "apps/api/src",
  "packages/api-contracts/python",
  "packages/analytical-schemas/python",
  "packages/atlas-interfaces/python",
  "packages/config/python",
  "packages/test-utils/python",
  "packages/overview-analytics/python",
  "packages/sql-lab-runtime/python",
].map((entry) => path.resolve(entry)).join(path.delimiter);

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
  use: { baseURL: externalBaseUrl ?? "http://127.0.0.1:3100", trace: "retain-on-failure" },
  // A developer may deliberately validate against an already-running local
  // stack (for example, the certified physical host) without Playwright
  // trying to bind a second API process to port 8000. CI still owns its
  // isolated servers because it never supplies this opt-in base URL.
  ...(externalBaseUrl ? {} : { webServer: [
    {
      command: `"${python}" -m uvicorn --app-dir "${apiDirectory}" prism_api.main:app --host 127.0.0.1 --port 8000`,
      url: "http://127.0.0.1:8000/api/v1/platform/health",
      reuseExistingServer: false,
      env: {
        PRISM_ALLOWED_ORIGINS: '["http://127.0.0.1:3100"]',
        PYTHONPATH: localPythonPath,
      }
    },
    {
      command: "npm run dev --workspace=@prism/web -- --port 3100",
      url: "http://127.0.0.1:3100",
      reuseExistingServer: false
    }
  ] }),
  projects: [
    { name: "live-chromium", use: { ...devices["Desktop Chrome"] } },
    {
      name: "live-mobile-chromium",
      testMatch: /atlas-accessibility-live\.spec\.ts/,
      use: { ...devices["Pixel 7"], viewport: { width: 390, height: 844 } }
    }
  ]
});
