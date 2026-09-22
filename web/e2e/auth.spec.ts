import { expect, test } from "@playwright/test";

/**
 * The sign-in journey, clicked through by a real browser.
 *
 * Uses the demo account created by `python scripts/seed.py`. Run the seed
 * first; these tests say so rather than creating their own account, because
 * registration needs a verification link that only exists in the API's log.
 */

const DEMO_EMAIL = "nora@acme.example";
/** The form's own alert.
 *
 * Not getByRole("alert"): Next.js keeps an empty role="alert" route
 * announcer in the page, so that selector matches two elements and fails in
 * strict mode. data-slot is what the design system stamps on its Alert. */
const formAlert = (page: import("@playwright/test").Page) =>
  page.locator('[data-slot="alert"]');
const DEMO_PASSWORD = "leka-demo-password";

test("an anonymous visitor is sent to sign in", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("a wrong password shows one message and reveals nothing", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(DEMO_EMAIL);
  await page.getByLabel("Password").fill("definitely not the password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(formAlert(page)).toBeVisible();
  await expect(formAlert(page)).toHaveText("Invalid email or password.");
});

test("an unknown address gives exactly the same message", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("nobody@nowhere.example");
  await page.getByLabel("Password").fill("definitely not the password");
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(formAlert(page)).toHaveText("Invalid email or password.");
});

test("the demo account signs in, sees its workspace, and signs out", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(DEMO_EMAIL);
  await page.getByLabel("Password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();

  // The whole point of the browser test: this only works if the session
  // cookie was actually stored and sent back. Since LEKA-337 the answer is
  // the application shell — the workspace on the sidebar, the account in the
  // menu — rather than the two lines the landing page used to print.
  // "/" redirects to the overview: every zone has a named path.
  await expect(page).toHaveURL("http://localhost:3000/overview");
  await expect(page.getByText("Acme Corp")).toBeVisible();

  await page.getByTestId("user-menu").last().click();
  await expect(page.getByText(DEMO_EMAIL)).toBeVisible();
  await page.getByTestId("sign-out").click();
  await expect(page).toHaveURL(/\/login$/);

  // And the session is genuinely gone, not just navigated away from.
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
});

test("the sign-in page links to registration and recovery", async ({ page }) => {
  await page.goto("/login");

  await page.getByRole("link", { name: "Create one" }).click();
  await expect(page.getByRole("heading", { name: "Create an account" })).toBeVisible();

  await page.getByRole("link", { name: "Sign in" }).click();
  await page.getByRole("link", { name: "Forgot it?" }).click();
  await expect(page.getByRole("heading", { name: "Reset your password" })).toBeVisible();
});

test("asking to reset a password never says whether the account exists", async ({ page }) => {
  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill("nobody@nowhere.example");
  await page.getByRole("button", { name: "Send reset link" }).click();

  await expect(page.getByRole("heading", { name: "Check your inbox" })).toBeVisible();
});
