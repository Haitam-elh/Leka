import AxeBuilder from "@axe-core/playwright";
import { expect, type Locator, type Page, test } from "@playwright/test";

import { openContextTab } from "./context-tab";
import { openIncidentAnalysis } from "./incident";
import { openNavigation, signIn } from "./sign-in";

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

/**
 * What the screen shows, then what a machine finds wrong in it. Shown is its
 * main content by default — or what is open above it: a modal hides the
 * rest from assistive technologies, as it should, so the main content is
 * then no landmark to wait for (it was, while the modal was still taking
 * over, which is why waiting for it passed only on a fast machine).
 */
async function expectNoViolations(page: Page, shown: Locator = page.getByRole("main")) {
  await expect(shown).toBeVisible();
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
    // An agent's product page (LEKA-471).
    "/capabilities/application-architecture",
    // The notification centre (LEKA-476).
    "/notifications",
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
  test("the bell's panel open, the latest told", async ({ page }) => {
    await signIn(page);
    await page.goto("/overview");
    await page.getByTestId("notifications-bell").click();
    await expect(page.getByTestId("notifications-panel")).toBeVisible();

    await expectNoViolations(page, page.getByTestId("notifications-panel"));
  });

  test("an agent's product page, a question of its FAQ and its technical details open", async ({ page }) => {
    await signIn(page);
    await page.goto("/capabilities/code-review#faq");
    await page.getByTestId("agent-faq-list").getByText("Peut-il modifier mes systèmes ?").click();
    await expect(page.getByText("Non. Il travaille en lecture seule et ne déclenche rien.")).toBeVisible();
    await page.getByTestId("agent-technical").getByText("Détails techniques").click();
    await expect(page.getByTestId("capability-technical")).toBeVisible();

    await expectNoViolations(page);
  });

  test("an entity's context, assembled, an element's provenance and the left out open", async ({
    page,
  }) => {
    await openContextTab(page);
    await page.getByRole("button", { name: "Assembler le contexte" }).click();
    await page
      .getByTestId("context-elements")
      .getByRole("button", { name: "Provenance de payment-api", exact: true })
      .click();
    await expect(page.getByTestId("context-provenance")).toBeVisible();
    // How it was ranked, what was left out (LEKA-372), open too.
    await expect(page.getByTestId("element-ranking")).toBeVisible();
    await page
      .getByTestId("context-left-out")
      .getByRole("button", { name: "Voir la liste" })
      .click();
    // How good it is, in detail (LEKA-375).
    await page.getByRole("button", { name: "Voir le détail des mesures" }).click();
    await expect(page.getByTestId("quality-retrieval")).toBeVisible();
    // The element inspected, its evidence asked for (LEKA-376).
    await page
      .getByTestId("element-inspect")
      .getByRole("button", { name: "Voir les preuves" })
      .click();
    await expect(page.getByTestId("element-evidence")).toBeVisible();

    await expectNoViolations(page);
  });

  test("the navigation, every section open", async ({ page }) => {
    await signIn(page);
    await page.goto("/environment?tab=applications");
    await openNavigation(page);
    await page.getByTestId("nav-section-capabilities-toggle").click();
    await page.getByTestId("nav-section-administration-toggle").click();
    await expect(page.getByTestId("nav-capabilities-mine")).toBeVisible();
    await expect(page.getByTestId("nav-sources")).toBeVisible();

    // The navigation is a modal here: it, not the page under it.
    await expectNoViolations(
      page,
      page.getByRole("dialog", { name: /^(Navigation principale|Main navigation)$/ }),
    );
  });

  test("an incident's analysis, unfolded, a probable cause's evidence open", async ({ page }) => {
    await openIncidentAnalysis(page);
    await page
      .getByTestId("probable-cause")
      .getByRole("button", { name: /Voir les éléments/ })
      .click();
    await expect(page.getByTestId("probable-cause").getByTestId("evidence")).toBeVisible();

    await expectNoViolations(page);
  });
});

test.describe("a new intention, read", () => {
  test("its step 2: what LEKA understood, what is missing, what it gathered", async ({ page }) => {
    await signIn(page);
    await page.goto("/intentions/new");
    await expect(page.getByRole("checkbox", { name: "acme/backend" })).toBeChecked();
    await page
      .getByTestId("intention-input")
      .fill("Qu'est-ce qui a changé sur payment-api cette semaine ?");
    // What LEKA understood, before it is launched (LEKA-439).
    await page.getByTestId("intention-submit").click();
    await expect(page.getByTestId("intention-review")).toBeVisible();
    await expectNoViolations(page);
    await page.getByTestId("intention-launch").click();
    // The context in detail, opened (LEKA-438 folds it): all of it checked.
    await page.getByText("Détail du contexte").click();
    await expect(page.getByTestId("intent-scope")).toBeVisible();
    await page.getByRole("button", { name: "Voir tous les éléments" }).click();

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
