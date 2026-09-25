import { defineConfig, devices } from "@playwright/test";

import { OUTBOX } from "./e2e/outbox";
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

  /**
   * Five seconds is a laptop's budget, not a runner's.
   *
   * Everything these tests assert on sits behind an API call, and the one
   * in the way of almost all of them is a password check: argon2id over
   * 64 MiB, three passes, chosen for exactly that cost. Here it measures
   * 180ms. CI gives it two shared cores that also carry Postgres, Redis,
   * the API, Next and a browser, and that is the one part of the stack
   * that gets slower rather than faster when the machine is busy.
   *
   * Raised on CI only, so a local run still fails fast and nobody waits
   * fifteen seconds to be told a selector is wrong. It is a ceiling on a
   * machine we do not control, not a target — a sign-in that genuinely
   * takes ten seconds is a defect, and the trace carries the timing.
   */
  timeout: process.env.CI ? 60_000 : 30_000,
  expect: { timeout: process.env.CI ? 15_000 : 5_000 },

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
      //
      // No real email either, whatever the developer's .env says: a test run
      // must not send mail through the company mailbox. The messages go to
      // the outbox file instead, which is where e2e/emails.spec.ts reads the
      // links it clicks (LEKA-330).
      command: `${pythonExecutable()} -m uvicorn leka.main:app --port 8000`,
      cwd: "../api",
      env: {
        LEKA_SESSION_COOKIE_SECURE: "false",
        LEKA_SMTP_HOST: "",
        LEKA_RESEND_API_KEY: "",
        LEKA_WEB_URL: "http://localhost:3000",
        LEKA_EMAIL_OUTBOX_FILE: OUTBOX,
      },
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
