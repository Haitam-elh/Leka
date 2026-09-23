import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * The system states of LEKA-343, provoked for real in a browser.
 *
 * Each one is a situation nobody meets while building a screen — the
 * connection gone, the API down, a role that does not open a page — and so
 * the one most likely to ship broken. Here they are caused, not described:
 * the network is cut, the API call is refused, the permissions are taken
 * away, and what the person would see is checked.
 */

test.describe("when the connection goes", () => {
  test("says so once, keeps the page readable, and says when it is back", async ({
    page,
    context,
  }) => {
    await signIn(page);
    const banner = page.getByTestId("offline-banner");
    await expect(banner).toBeEmpty();

    await context.setOffline(true);
    await expect(banner).toContainText("Vous êtes hors ligne");
    // What was on screen is still there to read.
    await expect(page.getByTestId("intention-input")).toBeVisible();

    await context.setOffline(false);
    await expect(banner).toContainText("Connexion rétablie.");
  });
});

test.describe("when the API does not answer", () => {
  test("offers a way forward instead of the error's own words", async ({ page }) => {
    await signIn(page);

    // From here on, the session check fails as if the API were down.
    await page.route("**/api/v1/auth/me", (route) => route.abort("connectionrefused"));
    await page.reload();

    const state = page.getByTestId("error-state-unreachable");
    await expect(state).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("LEKA ne répond pas");
    // What the shell used to print: "Cannot reach the API at http://…".
    await expect(page.locator("main")).not.toContainText("localhost");

    // The API comes back; the keyboard alone gets the page back.
    await page.unroute("**/api/v1/auth/me");
    await state.getByRole("button", { name: "Réessayer" }).focus();
    await page.keyboard.press("Enter");

    await expect(page.getByTestId("intention-input")).toBeVisible();
  });
});

test.describe("when a page is not for this person", () => {
  test("refuses it as the page's own title, with a way back", async ({ page }) => {
    // The real answer, minus the one permission /team needs.
    await page.route("**/api/v1/workspaces/current", async (route) => {
      const response = await route.fetch();
      const body = (await response.json()) as { permissions: string[] };
      await route.fulfill({
        response,
        json: { ...body, permissions: body.permissions.filter((p) => p !== "member:invite") },
      });
    });
    await signIn(page);

    await page.goto("/team");

    await expect(page.getByTestId("route-state-forbidden")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "Vous n'avez pas accès à cette page",
    );
    await expect(page.getByRole("link", { name: "Retour à la vue d'ensemble" })).toBeVisible();
  });
});

test.describe("when the address is wrong", () => {
  test("keeps the frame, titles the page, and leads back", async ({ page }) => {
    await signIn(page);
    await page.goto("/nothing/here");

    await expect(page.getByRole("navigation", { name: "Navigation principale" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Page introuvable");

    await page.getByRole("link", { name: "Retour à la vue d'ensemble" }).click();
    await expect(page).toHaveURL(/\/overview$/);
  });
});
