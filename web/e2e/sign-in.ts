import { expect, type Page, type Response } from "@playwright/test";

/**
 * Signing in, for the tests whose subject is what comes after it.
 *
 * It lived twice, once in each spec that needed it, which is how the two
 * copies came to disagree about how long a sign-in may take.
 *
 * The one thing it does that fill-and-click did not is look at the answer
 * to POST /auth/login. A 429 from the rate limiter, a 500, an API that
 * died between tests — all of those used to reach the test as "the URL
 * never changed", which is the one symptom that fits every possible cause,
 * and whoever read the failure in CI had to guess. The status is now in
 * the message.
 *
 * How long any of it may take is not decided here. It is in
 * playwright.config.ts, once, for every assertion in the suite, because
 * the slow part is the API and nearly every assertion waits on it.
 */

export const DEMO_EMAIL = "nora@acme.example";
export const DEMO_PASSWORD = "leka-demo-password";

/** Where a signed-in visitor lands. */
export const LANDING = "http://localhost:3000/overview";

/**
 * The answer to the sign-in, awaited from before the click.
 *
 * Called first, awaited after: a response that arrives between the two
 * would otherwise be missed, and the wait would hang on a request that has
 * already been and gone.
 */
export function loginAnswer(page: Page): Promise<Response> {
  return page.waitForResponse(
    (response) => response.url().endsWith("/auth/login") && response.request().method() === "POST",
  );
}

/** Assert the API actually let us in, and say what it answered if not. */
export function expectSignedIn(response: Response): void {
  expect(response.ok(), `POST /auth/login answered ${response.status()}`).toBe(true);
}

export async function signIn(page: Page): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(DEMO_EMAIL);
  await page.getByLabel("Password").fill(DEMO_PASSWORD);

  const answered = loginAnswer(page);
  await page.getByRole("button", { name: "Sign in" }).click();
  expectSignedIn(await answered);

  await expect(page).toHaveURL(LANDING);
}
