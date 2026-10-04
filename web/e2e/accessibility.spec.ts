import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

import { openContextTab } from "./context-tab";
import { signIn } from "./sign-in";

/**
 * The accessibility review of LEKA-343, as far as a machine can take it.
 *
 * Every core screen, and every system state that replaces one — because a
 * page that is accessible when it works and not when it fails fails the
 * people who most need it to say what happened.
 *
 * WCAG 2.1 A and AA, plus axe's best practices. The best practices are what
 * caught the two defects this ticket found: two unnamed "complementary"
 * regions on the new-intention screen, and a "not found" page with no
 * level-one heading. Neither is a WCAG failure on its own; both make a
 * screen reader user's first move — list the landmarks, jump to the h1 —
 * land nowhere.
 *
 * What a machine cannot judge — whether the wording helps, whether the
 * order of tabbing makes sense — is covered by the keyboard tests in the
 * other files and by docs/frontend/system-states.md.
 */

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"];

async function expectNoViolations(page: Page) {
  await expect(page.getByRole("main")).toBeVisible();
  const { violations } = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  // Named rather than counted: "expected 0, got 3" sends whoever reads the
  // failure to the report, and the report is in CI.
  expect(violations.map((violation) => `${violation.id}: ${violation.help}`)).toEqual([]);
}

test.describe("the core screens", () => {
  for (const path of [
    "/overview",
    "/intentions/new",
    "/intentions/new?step=decision",
    "/settings",
    "/sources",
    "/welcome",
    "/environment",
    "/environment/graph",
    "/governance",
  ]) {
    test(`${path} has no violation a machine can see`, async ({ page }) => {
      await signIn(page);
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

      await expectNoViolations(page);
    });
  }
});

test.describe("what a screen opens", () => {
  test("an entity's context, assembled, an element's provenance open", async ({ page }) => {
    await openContextTab(page);
    await page.getByRole("button", { name: "Assembler le contexte" }).click();
    await page
      .getByTestId("context-elements")
      .getByRole("button", { name: "Provenance de payment-api", exact: true })
      .click();
    await expect(page.getByTestId("context-provenance")).toBeVisible();

    await expectNoViolations(page);
  });
});

test.describe("the states that replace them", () => {
  test("an unknown address", async ({ page }) => {
    await signIn(page);
    await page.goto("/nothing/here");
    await expect(page.getByTestId("route-state-not-found")).toBeVisible();

    await expectNoViolations(page);
  });

  test("the API not answering", async ({ page }) => {
    await signIn(page);
    await page.route("**/api/v1/auth/me", (route) => route.abort("connectionrefused"));
    await page.reload();
    await expect(page.getByTestId("error-state-unreachable")).toBeVisible();

    await expectNoViolations(page);
  });

  test("the connection gone", async ({ page, context }) => {
    await signIn(page);
    await context.setOffline(true);
    await expect(page.getByTestId("offline-banner")).toContainText("hors ligne");

    await expectNoViolations(page);
    await context.setOffline(false);
  });
});

test.describe("before signing in", () => {
  for (const path of ["/login", "/register", "/forgot-password"]) {
    test(`${path} has no violation a machine can see`, async ({ page }) => {
      await page.goto(path);

      await expectNoViolations(page);
    });
  }
});
