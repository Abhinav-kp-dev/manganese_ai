// End-to-end smoke tests: the real FastAPI backend serving the built dashboard.
// Run: npm run build && npm run test:e2e   (needs the backend's Python requirements installed)
import { defineConfig, devices } from "@playwright/test";
import os from "node:os";
import path from "node:path";

const PORT = Number(process.env.E2E_PORT || 8765);
const DATA_DIR = process.env.E2E_DATA_DIR || path.join(os.tmpdir(), `mh-e2e-${process.pid}`);
const PYTHON = process.env.PYTHON || "python";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure", ...devices["Desktop Chrome"] },
  webServer: {
    command: `${PYTHON} -m uvicorn app.main:app --host 127.0.0.1 --port ${PORT}`,
    cwd: path.resolve("../backend"),
    url: `http://127.0.0.1:${PORT}/api/health`,
    timeout: 240_000,
    reuseExistingServer: false,
    env: { ...process.env, MH_DATA_DIR: DATA_DIR, MH_SYNC_BOOTSTRAP: "1", MH_PIPELINE_INTERVAL_MIN: "0" },
  },
});
