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
  await page.getByLabel("Adresse e-mail", { exact: true }).fill(DEMO_EMAIL);
  await page.getByLabel("Mot de passe", { exact: true }).fill(DEMO_PASSWORD);

  const answered = loginAnswer(page);
  await page.getByRole("button", { name: "Se connecter" }).click();
  expectSignedIn(await answered);

  await expect(page).toHaveURL(LANDING);
  await expectShellReady(page);
}

/**
 * Wait until the application is usable, not merely until the URL changed.
 *
 * THE BUG THIS CLOSES. Signing in put the address bar on /overview and
 * returned. The shell had not finished: it asks /auth/me, then
 * /workspaces/current, and it draws no navigation until it knows what this
 * person may open. Every test that ran straight after was racing those two
 * calls, and the race was invisible on a fast machine.
 *
 * On CI it surfaced as three different tests failing on three different
 * elements across two runs of the same commit — nav-overview missing,
 * nav-sources missing, and once a bounce back to /login, which is the same
 * shell reporting that a call came back 401. One cause, three disguises,
 * and no way to see it from any of them.
 *
 * Waiting for the plan in the header is waiting for the session to have
 * arrived (LEKA-455: no sidebar any more), since it reads the workspace's. A failure now
 * happens here, under this name, instead of in whichever test drew the
 * short straw.
 */
export async function expectShellReady(page: Page): Promise<void> {
  try {
    // A public plan's badge, or an Enterprise contract's (2026-10-25).
    await expect(page.getByTestId("plan-badge").or(page.getByTestId("enterprise-badge"))).toBeVisible();
  } catch {
    // The shell has three ways of failing and it prints all of them: a
    // loading message that never resolved, "the API is unreachable", or
    // the detail of whatever came back. A 401 shows up as the address
    // being /login again. Any of those answers the question; "element not
    // found" answers none of it, and that is what CI reported three times
    // on the same commit.
    const said = (await page.getByRole("main").textContent())?.trim() ?? "(nothing)";
    throw new Error(
      `The shell never became usable.\n  URL:  ${page.url()}\n  Says: ${said.slice(0, 300)}`,
    );
  }
}
