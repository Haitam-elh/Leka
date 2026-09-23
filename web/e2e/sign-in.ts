import { expect, type Page } from "@playwright/test";

/**
 * Signing in, for the tests whose subject is what comes after it.
 *
 * It lived twice, once in each spec that needed it, which is how the two
 * copies came to disagree about how long a sign-in may take.
 *
 * TWO THINGS IT DOES THAT FILL-AND-CLICK DID NOT.
 *
 * It looks at the answer to POST /auth/login. A 429 from the rate limiter,
 * a 500, an API that died between tests — all of those used to reach the
 * test as "the URL never changed", which is the one symptom that fits every
 * possible cause, and whoever read the failure in CI had to guess. The
 * status is now in the message.
 *
 * And it allows the landing far more than Playwright's five seconds. That
 * default is tuned for the machine the tests are written on, where this
 * whole sequence measures 180ms. CI runs it on two shared cores that also
 * host Postgres, Redis, the API and a browser, and the password check is
 * argon2id over 64 MiB, three passes — deliberately expensive, and the part
 * of this that gets slower, not faster, when the machine is busy. Add the
 * two round trips of / redirecting to /overview and five seconds is a
 * budget a healthy run can exceed. It did, once, on the 22nd sign-in of a
 * run in which the other 24 tests passed.
 *
 * The number is a ceiling on a machine we do not control, not a target: a
 * sign-in that genuinely takes ten seconds is a defect, and the timing is
 * in the trace when it happens.
 */

export const DEMO_EMAIL = "nora@acme.example";
export const DEMO_PASSWORD = "leka-demo-password";

/** Where a signed-in visitor lands. */
export const LANDING = "http://localhost:3000/overview";

const LANDING_TIMEOUT_MS = 15_000;

export async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(DEMO_EMAIL);
  await page.getByLabel("Password").fill(DEMO_PASSWORD);

  const answered = page.waitForResponse(
    (response) => response.url().endsWith("/auth/login") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Sign in" }).click();
  const response = await answered;
  expect(response.ok(), `POST /auth/login answered ${response.status()}`).toBe(true);

  await expect(page).toHaveURL(LANDING, { timeout: LANDING_TIMEOUT_MS });
}
