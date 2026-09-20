import { defineConfig, devices } from "@playwright/test";

import { pythonExecutable } from "./e2e/python";

/**
 * End-to-end tests in a real browser.
 *
 * These exist because of a specific class of bug that no unit test can see.
 * Cookie rules — Secure, SameSite, and what counts as "the same site" — are
 * enforced by the browser and by nothing else. Two of the defects found in
 * LEKA-330 were exactly that: the app compiled, every test passed, and
 * signing in could not have worked in a browser.
 *
 * Both servers are started here rather than by hand, so running this is one
 * command and CI can run the same one.
 */
export default defineConfig({
  testDir: "./e2e",
  // Seeds the demo workspace and its account before anything runs.
  globalSetup: "./e2e/global-setup.ts",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [["list"]],

  use: {
    // localhost, not 127.0.0.1: the browser treats them as different sites,
    // and a SameSite=Lax cookie set by one is never sent to the other.
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: [
    {
      // The API. Secure cookies are turned off because these tests speak
      // http: a browser refuses to store a Secure cookie over a plain
      // connection, which would make every sign-in silently fail. The
      // production configuration is asserted separately, in the Python
      // suite, where it does not need a browser.
      command: `${pythonExecutable()} -m uvicorn leka.main:app --port 8000`,
      cwd: "../api",
      env: { LEKA_SESSION_COOKIE_SECURE: "false" },
      url: "http://localhost:8000/api/v1/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: "npm run start",
      url: "http://localhost:3000/login",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
