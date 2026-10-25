import { expect, test, type Page } from "@playwright/test";

import { ask, openStep } from "./intention-helpers";
import { LANDING, signIn } from "./sign-in";

/**
 * The information architecture, clicked through.
 *
 * What a unit test cannot answer: that every route in the registry actually
 * renders, inside the shell, with the right entry marked, the right trail
 * above the title and the right words in the browser tab.
 */

/** Every page, the header's entry it marks (LEKA-494), the title it carries. */
const ZONES = [
  ["/overview", "home", "Mon Dashboard"],
  ["/intentions/new", "history", "Nouvelle intention"],
  ["/intentions", "history", "Intentions"],
  ["/environment", "environment", "Mon environnement"],
  ["/capabilities", "agents", "Compétences"],
  ["/activity", null, "Activité"],
  ["/approvals", null, "À valider"],
  ["/sources", null, "Sources"],
  ["/governance", null, "Sécurité"],
  ["/team", null, "Équipe"],
  ["/billing", null, "Facturation"],
  ["/settings", null, "Paramètres"],
] as const;

test.describe("the information architecture", () => {
  test("gives every zone the same shell, the right entry and the right title", async ({ page }) => {
    await signIn(page);
    const header = page.getByRole("navigation", { name: "Navigation principale" });

    for (const [path, id, label] of ZONES) {
      await page.goto(path);
      await expect(page).toHaveTitle(`${label} · LEKA`);
      // Its entry marked in the header — the only one; none for a page of
      // running the workspace, in the profile menu.
      await expect(header.locator('a[aria-current="page"]')).toHaveCount(id ? 1 : 0);
      if (id) await expect(page.getByTestId(`nav-${id}`)).toHaveAttribute("aria-current", "page");
    }
  });

  test("no grid, no drawer: the main pages in the header, the others in the profile menu (LEKA-494)", async ({
    page,
  }) => {
    await signIn(page);
    await expect(page.getByTestId("open-navigation")).toHaveCount(0);
    for (const id of ["home", "environment", "agents", "history"]) {
      await expect(page.getByTestId(`nav-${id}`)).toBeVisible();
    }

    for (const [id, path] of [
      ["sources", "/sources"],
      ["governance", "/governance"],
      ["team", "/team"],
      ["billing", "/billing"],
    ] as const) {
      await page.getByTestId("user-menu").click();
      await page.getByTestId(`menu-${id}`).click();
      await expect(page).toHaveURL(`http://localhost:3000${path}`);
    }

    // A phone: the header has no room for them — the profile menu holds them.
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByTestId("nav-environment")).toBeHidden();
    await page.getByTestId("user-menu").click();
    await page.getByTestId("menu-environment").click();
    await expect(page).toHaveURL("http://localhost:3000/environment");
  });

  test("puts a trail above a detail page, and names the thing you opened", async ({ page }) => {
    await signIn(page);
    await page.goto("/environment/services/payment-api");

    const trail = page.getByRole("navigation", { name: "Fil d'Ariane" });
    await expect(trail.getByRole("link", { name: "Mon environnement" })).toBeVisible();
    await expect(trail.getByText("Payment API")).toBeVisible();
    await expect(page).toHaveTitle("Payment API · LEKA");
    // The parent stays marked while you read one of its children.
    await expect(page.getByTestId("nav-environment")).toHaveAttribute("aria-current", "page");
  });

  test("keeps a tab in the URL, so it can be sent to someone", async ({ page }) => {
    await signIn(page);
    const id = await ask(page, `Qui est responsable de auth-service ? (${Date.now()})`);

    // Its bare address opens its page (LEKA-458); each step's view, its own.
    await expect(page.getByTestId("intention-detail-page")).toBeVisible();

    await openStep(page, "evidence");

    await expect(page).toHaveURL(`http://localhost:3000/intentions/${id}/evidence`);
    await expect(page.getByTestId("tab-evidence")).toHaveAttribute("aria-current", "page");
    // Reloading the shared link lands on the same tab.
    await page.reload();
    await expect(page.getByTestId("tab-evidence")).toHaveAttribute("aria-current", "page");
  });

  test("opens Sécurité on who may do what, and the trail of decisions", async ({
    page,
  }) => {
    await signIn(page);

    // Every page is built now — Gouvernance was the last (LEKA-402). The
    // "not built yet" and "not on this plan" states stay covered by
    // route-views.test.tsx.
    await page.goto("/governance");
    // The overview first (LEKA-438): real figures, the trail of decisions.
    await expect(page.getByTestId("governance-overview")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Journal des accès" })).toBeVisible();
    // « Accès » exactly: « Sessions et accès » is another tab (2026-10-25).
    await page.getByRole("tab", { name: "Accès", exact: true }).click();
    await expect(page).toHaveURL(/\/governance\?tab=access$/);
    await expect(page.getByTestId("access-matrix")).toContainText("Restreindre une entité");
    // A creation form opens in a dialog, and Escape closes it.
    await page.getByRole("button", { name: "Nouveau rôle" }).click();
    await expect(page.getByRole("dialog", { name: "Nouveau rôle" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);

    // Sessions et accès (2026-10-25): this device, said as such, never signed
    // out from here; what LEKA keeps.
    await page.getByRole("tab", { name: "Sessions et accès" }).click();
    await expect(page).toHaveURL(/\/governance\?tab=security$/);
    const current = page.locator('[data-testid="device-session"][data-current="true"]');
    await expect(current).toContainText("Cet appareil");
    await expect(current.getByTestId("device-sign-out")).toHaveCount(0);
    await expect(page.getByTestId("security-stored")).toContainText("jamais son contenu");
    // Usage des agents: counted over a period, never priced.
    await page.getByRole("tab", { name: "Usage des agents" }).click();
    await expect(page).toHaveURL(/\/governance\?tab=agents$/);
    await expect(page.getByTestId("agent-usage-tab")).toBeVisible();
    await expect(page.getByTestId("agent-usage-tab")).not.toContainText("€");
  });

  test("keeps the shell around an address that matches nothing", async ({ page }) => {
    await signIn(page);
    await page.goto("/there-is-no-such-page");

    // Not a bare 404: dropping the shell here reads as "you were logged out".
    await expect(page.getByTestId("home-logo")).toBeVisible();
    await expect(page.getByTestId("route-state-not-found")).toBeVisible();
    await page.getByRole("link", { name: "Retour à la vue d'ensemble" }).click();
    await expect(page).toHaveURL("http://localhost:3000/overview");
  });
});

test.describe("the three pillars (LEKA-428)", () => {
  test("opens « Mon environnement » on its overview, its views chosen top right, by their address", async ({
    page,
  }) => {
    await signIn(page);

    // The header's entry opens its overview.
    await page.getByTestId("nav-environment").click();
    await expect(page).toHaveURL("http://localhost:3000/environment");
    await expect(page.getByRole("tablist", { name: "Vue de l'environnement" }).getByRole("tab", { name: "Vue d'ensemble" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("nav-environment")).toHaveAttribute("aria-current", "page");

    // A view chosen on the page (LEKA-459: its tabs): in the address, the
    // menu still on its page.
    await page.getByRole("tablist", { name: "Vue de l'environnement" }).getByRole("tab", { name: "Services" }).click();
    await expect(page).toHaveURL("http://localhost:3000/environment?tab=applications");
    await expect(page.getByRole("tablist", { name: "Vue de l'environnement" }).getByRole("tab", { name: "Services" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("nav-environment")).toHaveAttribute("aria-current", "page");

    // And the address is the view: reloaded, or sent, it opens there.
    await page.goto("/environment?tab=domains");
    await expect(page.getByTestId("env-more")).toContainText("Domaines");
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
    // The plan opens the plans compared, which a member reads (LEKA-466) —
    // never Facturation.
    await expect(page.getByTestId("plan-badge")).toHaveAttribute("href", "/billing/plans");

    await expect(page.getByTestId("nav-environment")).toBeVisible();
    await page.getByTestId("user-menu").click();
    await expect(page.getByTestId("settings")).toBeVisible();
    await expect(page.getByTestId("menu-sources")).toBeVisible();
    await expect(page.getByTestId("menu-billing")).toHaveCount(0);
    await expect(page.getByTestId("menu-team")).toHaveCount(0);
    await expect(page.getByTestId("nav-approvals")).toHaveCount(0);
    await page.keyboard.press("Escape");

    await page.goto("/billing");

    // In the shell, with a way out: not a 404, and not a silent redirect.
    await expect(page.getByTestId("home-logo")).toBeVisible();
    await expect(page.getByTestId("route-state-forbidden")).toBeVisible();
    await expect(page.getByRole("link", { name: "Retour à la vue d'ensemble" })).toBeVisible();
  });
});
