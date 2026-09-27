import { expect, test } from "@playwright/test";

import {
  DEMO_EMAIL,
  DEMO_PASSWORD,
  LANDING,
  expectSignedIn,
  loginAnswer,
} from "./sign-in";

/**
 * The sign-in journey, clicked through by a real browser.
 *
 * Uses the demo account created by `python scripts/seed.py` (global-setup
 * runs it). Creating an account from its email is emails.spec.ts.
 */

/** The form's own alert.
 *
 * Not getByRole("alert"): Next.js keeps an empty role="alert" route
 * announcer in the page, so that selector matches two elements and fails in
 * strict mode. data-slot is what the design system stamps on its Alert. */
const formAlert = (page: import("@playwright/test").Page) =>
  page.locator('[data-slot="alert"]');

test("an anonymous visitor is sent to sign in", async ({ page }) => {
  // "/" is leka-core.com's home page since the site and the application
  // became one (site.spec.ts); any page of the application sends to sign in.
  await page.goto("/overview");

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Se connecter à LEKA" })).toBeVisible();
});

test("a wrong password shows one message and reveals nothing", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Adresse e-mail", { exact: true }).fill(DEMO_EMAIL);
  await page.getByLabel("Mot de passe", { exact: true }).fill("definitely not the password");
  await page.getByRole("button", { name: "Se connecter" }).click();

  await expect(formAlert(page)).toBeVisible();
  await expect(formAlert(page)).toHaveText("Adresse e-mail ou mot de passe incorrect.");
});

test("an unknown address gives exactly the same message", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Adresse e-mail", { exact: true }).fill("nobody@nowhere.example");
  await page.getByLabel("Mot de passe", { exact: true }).fill("definitely not the password");
  await page.getByRole("button", { name: "Se connecter" }).click();

  await expect(formAlert(page)).toHaveText("Adresse e-mail ou mot de passe incorrect.");
});

test("the demo account signs in, sees its workspace, and signs out", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Adresse e-mail", { exact: true }).fill(DEMO_EMAIL);
  await page.getByLabel("Mot de passe", { exact: true }).fill(DEMO_PASSWORD);
  const answered = loginAnswer(page);
  await page.getByRole("button", { name: "Se connecter" }).click();
  // Read the answer rather than infer it from a URL that did not change:
  // a refusal and a slow reply look identical from the address bar, and
  // this test is the one that should say which it was.
  expectSignedIn(await answered);

  // The whole point of the browser test: this only works if the session
  // cookie was actually stored and sent back. Since LEKA-337 the answer is
  // the application shell — the workspace on the sidebar, the account in the
  // menu — rather than the two lines the landing page used to print.
  await expect(page).toHaveURL(LANDING);
  await expect(page.getByText("Acme Corp")).toBeVisible();

  await page.getByTestId("user-menu").last().click();
  await expect(page.getByText(DEMO_EMAIL)).toBeVisible();
  await page.getByTestId("sign-out").click();
  // Back to leka-core.com's home page, where people come in from.
  await expect(page).toHaveURL("http://localhost:3000/");

  // And the session is genuinely gone, not just navigated away from — a
  // reload, then the application, sends to sign in.
  await page.reload();
  await page.goto("/overview");
  await expect(page).toHaveURL(/\/login$/);
});

test("signing out leaves the application even when the API call fails", async ({ page }) => {
  // The regression behind LEKA-337's intermittent failure. Signing out used
  // to navigate only if POST /auth/logout resolved: any failure threw out of
  // the click handler, nothing caught it, and the person stayed on the page
  // with no sign that the button had done anything. In CI that showed up as
  // a sign-out test that failed once in a while and passed on a re-run.
  //
  // Aborting the call reproduces it on demand rather than waiting for the
  // network to misbehave on its own.
  await page.goto("/login");
  await page.getByLabel("Adresse e-mail", { exact: true }).fill(DEMO_EMAIL);
  await page.getByLabel("Mot de passe", { exact: true }).fill(DEMO_PASSWORD);
  const answered = loginAnswer(page);
  await page.getByRole("button", { name: "Se connecter" }).click();
  expectSignedIn(await answered);
  // Waits for the shell rather than for a URL: this test is about leaving,
  // and where signing in lands is someone else's decision to change.
  await expect(page.getByTestId("user-menu").last()).toBeVisible();

  await page.route("**/auth/logout", (route) => route.abort());

  await page.getByTestId("user-menu").last().click();
  await page.getByTestId("sign-out").click();

  // On the site's home page, with no ?next= pointing back into the
  // application.
  await expect(page).toHaveURL("http://localhost:3000/");
  // The session outlived the failed call, yet the site's "Se connecter"
  // shows the form: someone who asked to leave is not let straight back in.
  await page.locator("header").getByRole("link", { name: "Se connecter" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Se connecter à LEKA" })).toBeVisible();
});

test("a session nobody asked to remember ends with the browser", async ({ page, context }) => {
  await page.goto("/login");
  await page.getByLabel("Adresse e-mail", { exact: true }).fill(DEMO_EMAIL);
  await page.getByLabel("Mot de passe", { exact: true }).fill(DEMO_PASSWORD);
  const answered = loginAnswer(page);
  await page.getByRole("button", { name: "Se connecter" }).click();
  expectSignedIn(await answered);

  const session = (await context.cookies()).find((c) => c.name === "leka_session");
  expect(session?.expires).toBe(-1); // a session cookie: gone when the browser closes
});

test("a device asked to remember keeps the session", async ({ page, context }) => {
  await page.goto("/login");
  await page.getByLabel("Adresse e-mail", { exact: true }).fill(DEMO_EMAIL);
  await page.getByLabel("Mot de passe", { exact: true }).fill(DEMO_PASSWORD);
  await page.getByLabel("Se souvenir de cet appareil").check();
  const answered = loginAnswer(page);
  await page.getByRole("button", { name: "Se connecter" }).click();
  expectSignedIn(await answered);

  const session = (await context.cookies()).find((c) => c.name === "leka_session");
  const inADay = Date.now() / 1000 + 24 * 3600;
  expect(session?.expires ?? 0).toBeGreaterThan(inADay);
});

test("the sign-in page links to registration and recovery", async ({ page }) => {
  await page.goto("/login");

  await page.getByRole("link", { name: "En créer un" }).click();
  await expect(page.getByRole("heading", { name: "Créer un compte" })).toBeVisible();

  // The card's own link: the site's header above has a "Se connecter" too.
  await page.getByRole("main").getByRole("link", { name: "Se connecter" }).click();
  await page.getByRole("link", { name: "Mot de passe oublié ?" }).click();
  await expect(
    page.getByRole("heading", { name: "Réinitialiser votre mot de passe" }),
  ).toBeVisible();
});

test("asking to reset a password never says whether the account exists", async ({ page }) => {
  await page.goto("/forgot-password");
  await page.getByLabel("Adresse e-mail", { exact: true }).fill("nobody@nowhere.example");
  await page.getByRole("button", { name: "Envoyer le lien" }).click();

  await expect(
    page.getByRole("heading", { name: "Consultez votre boîte de réception" }),
  ).toBeVisible();
});

test("an API that does not answer is said plainly, not quoted", async ({ page }) => {
  // What the sign-in page used to show here, in English on a French page:
  // "Cannot reach the API at http://localhost:8000. Is it running?"
  await page.route("**/api/v1/auth/login", (route) => route.abort("connectionrefused"));
  await page.goto("/login");
  await page.getByLabel("Adresse e-mail", { exact: true }).fill(DEMO_EMAIL);
  await page.getByLabel("Mot de passe", { exact: true }).fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();

  await expect(formAlert(page)).toHaveText(
    "LEKA ne répond pas pour le moment. Réessayez dans quelques instants.",
  );
});

test("a reset link is not promised when the request never left", async ({ page }) => {
  // "A reset link is on its way" is the answer whatever the server says —
  // whether an account exists is not ours to reveal. A request that never
  // reached the server is not an answer, and the promise would be untrue.
  await page.route("**/api/v1/auth/password/forgot", (route) =>
    route.abort("connectionrefused"),
  );
  await page.goto("/forgot-password");
  await page.getByLabel("Adresse e-mail", { exact: true }).fill("nobody@nowhere.example");
  await page.getByRole("button", { name: "Envoyer le lien" }).click();

  await expect(formAlert(page)).toContainText("LEKA ne répond pas");
  await expect(
    page.getByRole("heading", { name: "Consultez votre boîte de réception" }),
  ).toBeHidden();
});
