import { expect, test, type Page } from "@playwright/test";

import { LANDING, signIn } from "./sign-in";

/**
 * The information architecture, clicked through.
 *
 * What a unit test cannot answer: that every route in the registry actually
 * renders, inside the shell, with the right entry marked, the right trail
 * above the title and the right words in the browser tab.
 */

/** Every entry of the sidebar, with the title its page must carry. */
const ZONES = [
  ["/overview", "overview", "Vue d'ensemble"],
  ["/intentions", "intentions", "Intentions"],
  ["/approvals", "approvals", "À valider"],
  ["/activity", "activity", "Activité"],
  ["/environment", "environment", "Mon environnement"],
  ["/sources", "sources", "Sources"],
  ["/capabilities", "capabilities", "Capacités"],
  ["/governance", "governance", "Sécurité & gouvernance"],
  ["/team", "team", "Équipe & accès"],
  ["/billing", "billing", "Facturation"],
  ["/settings", "settings", "Paramètres"],
] as const;

test.describe("the information architecture", () => {
  test("gives every zone the same shell, the right entry and the right title", async ({ page }) => {
    await signIn(page);

    for (const [path, id, label] of ZONES) {
      await page.goto(path);

      await expect(page.getByRole("navigation", { name: "Navigation principale" })).toBeVisible();
      await expect(page.getByTestId(`nav-${id}`)).toHaveAttribute("aria-current", "page");
      await expect(page.locator('a[aria-current="page"]')).toHaveCount(1);
      await expect(page).toHaveTitle(`${label} · LEKA`);
    }
  });

  test("marks the button, not the list, on the intention composer", async ({ page }) => {
    await signIn(page);

    await page.getByTestId("new-intention").click();

    await expect(page).toHaveURL("http://localhost:3000/intentions/new");
    await expect(page.getByTestId("new-intention")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("nav-intentions")).not.toHaveAttribute("aria-current", "page");
  });

  test("puts a trail above a detail page, and names the thing you opened", async ({ page }) => {
    await signIn(page);
    await page.goto("/environment/services/payment-api");

    const trail = page.getByRole("navigation", { name: "Breadcrumb" });
    await expect(trail.getByRole("link", { name: "Mon environnement" })).toBeVisible();
    await expect(trail.getByText("Payment API")).toBeVisible();
    await expect(page).toHaveTitle("Payment API · LEKA");
    // The parent stays marked while you read one of its children.
    await expect(page.getByTestId("nav-environment")).toHaveAttribute("aria-current", "page");
  });

  test("keeps a tab in the URL, so it can be sent to someone", async ({ page }) => {
    await signIn(page);
    await page.goto("/intentions/42");

    await expect(page.getByTestId("tab-overview")).toHaveAttribute("aria-current", "page");

    await page.getByTestId("tab-evidence").click();

    await expect(page).toHaveURL("http://localhost:3000/intentions/42/evidence");
    await expect(page.getByTestId("tab-evidence")).toHaveAttribute("aria-current", "page");
    // Reloading the shared link lands on the same tab.
    await page.reload();
    await expect(page.getByTestId("tab-evidence")).toHaveAttribute("aria-current", "page");
  });

  test("says when a page is not built yet, rather than showing an empty one", async ({ page }) => {
    await signIn(page);

    await page.goto("/capabilities");
    await expect(page.getByTestId("route-state-unavailable")).toBeVisible();

    await page.goto("/governance");
    await expect(page.getByTestId("route-state-plan-gated")).toBeVisible();
  });

  test("keeps the shell around an address that matches nothing", async ({ page }) => {
    await signIn(page);
    await page.goto("/there-is-no-such-page");

    // Not a bare 404: dropping the sidebar here reads as "you were logged out".
    await expect(page.getByRole("navigation", { name: "Navigation principale" })).toBeVisible();
    await expect(page.getByTestId("route-state-not-found")).toBeVisible();
    await page.getByRole("link", { name: "Retour à la vue d'ensemble" }).click();
    await expect(page).toHaveURL("http://localhost:3000/overview");
  });
});

test.describe("the command palette", () => {
  test("opens with the keyboard and takes you where you asked", async ({ page }) => {
    await signIn(page);

    await page.keyboard.press("ControlOrMeta+k");
    await expect(page.getByTestId("palette-input")).toBeFocused();

    await page.getByTestId("palette-input").fill("sources");
    // Waits for the entry it is about to choose. Pressing the arrow key at
    // a list that is still being built is how this test used to pass: the
    // wrap-around landed on the only item there was.
    await expect(page.getByTestId("palette-sources")).toBeVisible();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");

    await expect(page).toHaveURL("http://localhost:3000/sources");
  });

  test("refuses to act on a list it has not finished building", async ({ page }) => {
    // The defect this stands over was invisible on a fast machine. The
    // palette read "we have not asked yet" as "this person may do nothing",
    // offered a navigation section with nothing in it, and the arrow key
    // wrapped around to the one action that is always there — so Enter
    // created an intention instead of going where the person asked.
    //
    // /workspaces/current is what carries the permissions, so holding it
    // open makes that window wide enough to act inside of.
    // Sign in first, with nothing slowed down: signIn waits for the shell to
    // be usable, and it cannot do that while the call carrying the
    // permissions is being held open. The delay goes on afterwards, and
    // reloading the page puts the shell back into the window this test is
    // about.
    await signIn(page);

    await page.route("**/api/v1/workspaces/current", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 3_000));
      await route.continue();
    });
    await page.goto("/overview");

    await page.keyboard.press("ControlOrMeta+k");
    await page.getByTestId("palette-input").fill("sources");
    await expect(page.getByTestId("palette-loading")).toBeVisible();

    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");

    // Nothing to choose means nothing chosen: still where it was.
    await expect(page).toHaveURL(LANDING);

    // And the entry appears once the answer does.
    await expect(page.getByTestId("palette-sources")).toBeVisible();
  });

  test("offers to create an intention with what was typed", async ({ page }) => {
    await signIn(page);

    await page.getByTestId("open-search").click();
    await page.getByTestId("palette-input").fill("pourquoi le paiement est lent ?");

    await expect(page.getByTestId("palette-create-intention")).toContainText(
      "pourquoi le paiement est lent ?",
    );
    // It offers the workflow; it never answers in the palette.
    await expect(page.getByTestId("palette-no-results")).toBeVisible();

    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/intentions\/new\?q=/);
  });

  test("closes on Escape and gives the keyboard back", async ({ page }) => {
    await signIn(page);

    await page.getByTestId("open-search").click();
    await expect(page.getByTestId("palette-input")).toBeVisible();

    await page.keyboard.press("Escape");

    await expect(page.getByTestId("palette-input")).toBeHidden();
    await expect(page.getByTestId("open-search")).toBeFocused();
  });
});

test.describe("what a member may see", () => {
  /**
   * The seed has one account, an owner. Rather than inventing a second one
   * through a verification e-mail, the API's answer is replaced: this test
   * is about what the interface does with a permission list, and that is
   * exactly what is being substituted.
   */
  async function asAMember(page: Page) {
    await page.route("**/api/v1/workspaces/current", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          workspace: { id: "w1", name: "Acme Corp", slug: "acme", status: "active" },
          role: "member",
          permissions: [
            "workspace:read",
            "member:read",
            "source:read",
            "intention:read",
            "intention:create",
          ],
        }),
      });
    });
  }

  test("hides billing, and refuses it politely when typed by hand", async ({ page }) => {
    await signIn(page);
    await asAMember(page);
    await page.goto("/overview");

    await expect(page.getByTestId("nav-billing")).toBeHidden();
    await expect(page.getByTestId("nav-environment")).toBeVisible();

    await page.goto("/billing");

    // In the shell, with a way out: not a 404, and not a silent redirect.
    await expect(page.getByRole("navigation", { name: "Navigation principale" })).toBeVisible();
    await expect(page.getByTestId("route-state-forbidden")).toBeVisible();
    await expect(page.getByRole("link", { name: "Retour à la vue d'ensemble" })).toBeVisible();
  });
});
