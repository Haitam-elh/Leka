import { expect, test } from "@playwright/test";

import { accountLanguage } from "./account-language";
import { signIn } from "./sign-in";

/**
 * The shell, in a real browser, at the sizes it claims to support (LEKA-455:
 * the sprint's mockups — a header, no permanent sidebar, every page in the
 * header's menu).
 *
 * Three things a unit test cannot answer: that the frame is the same on
 * every route, that it holds at each size rather than overflowing, and that
 * the skip link actually moves focus.
 *
 * Uses the demo account from `python scripts/seed.py`, like the sign-in
 * journey beside it.
 */

/** The viewports the ticket supports: laptop, small desktop, desktop, phone. */
const SIZES = [
  { name: "1440", width: 1440, height: 900 },
  { name: "1280", width: 1280, height: 800 },
  { name: "1024", width: 1024, height: 768 },
  { name: "390", width: 390, height: 844 },
] as const;

test.describe("the shell", () => {
  test("is the same frame on every area of the product, the way home on each", async ({ page }) => {
    await signIn(page);
    // The home has no way back to itself.
    await expect(page.getByTestId("back-home")).toHaveCount(0);

    for (const [href, id] of [
      ["/intentions", "history"],
      ["/sources", null],
      ["/team", null],
    ] as const) {
      await page.goto(href);

      await expect(page.getByTestId("home-logo")).toBeVisible();
      await expect(page.getByTestId("workspace-switcher")).toBeVisible();
      await expect(page.getByTestId("plan-badge")).toBeVisible();
      await expect(page.getByTestId("user-menu").first()).toBeVisible();
      await expect(page.locator("main#main-content")).toBeVisible();
      await expect(page.getByTestId("back-home")).toBeVisible();

      // The header marks the page you are on, and only that one — none for
      // a page of the profile menu (LEKA-494).
      await expect(page.getByRole("navigation", { name: "Navigation principale" }).locator('a[aria-current="page"]')).toHaveCount(id ? 1 : 0);
      if (id) await expect(page.getByTestId(`nav-${id}`)).toHaveAttribute("aria-current", "page");
    }

    await page.getByTestId("back-home").click();
    await expect(page).toHaveURL(/\/overview$/);
  });

  for (const size of SIZES) {
    test(`fits at ${size.name}px without a horizontal scrollbar`, async ({ page }) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      await signIn(page);

      // Nothing sticks out sideways: the one thing a shell gets wrong first.
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);

      // The content scrolls, the frame does not.
      await expect(page.locator("header").first()).toBeVisible();
      await expect(page.locator("main#main-content")).toBeVisible();
    });
  }

  test("takes you to the plans compared from the plan, Facturation still its own", async ({ page }) => {
    await signIn(page);
    await page.getByTestId("plan-badge").click();
    // LEKA-466: the five plans, the workspace's marked.
    await expect(page).toHaveURL(/\/billing\/plans$/);
    await expect(page.getByTestId("plan-card")).toHaveCount(5);
    await expect(page.locator('[data-testid="plan-card"][data-current="true"]')).toHaveCount(1);
    await page.getByRole("link", { name: /Facturation, factures/ }).click();
    await expect(page).toHaveURL(/\/billing$/);
  });

  test("lets the keyboard skip the header", async ({ page }) => {
    await signIn(page);

    const skip = page.getByRole("link", { name: "Aller au contenu" });

    // Not "the first Tab": `next dev` injects its own dev-tools button into
    // the page, and it takes a tab stop that production does not have. What
    // matters is that the skip link comes BEFORE the header's controls.
    for (let press = 0; press < 3; press += 1) {
      await page.keyboard.press("Tab");
      if (await skip.evaluate((node) => node === document.activeElement)) break;

      const inTheHeader = await page.evaluate(
        () => document.activeElement?.closest("header") !== null,
      );
      expect(inTheHeader, "the header was reached before the skip link").toBe(false);
    }

    await expect(skip).toBeFocused();

    await page.keyboard.press("Enter");
    await expect(page.locator("main#main-content")).toBeFocused();
  });

  test("changes language from the account menu", async ({ page }) => {
    await signIn(page);

    try {
      await page.getByTestId("user-menu").first().click();
      await page.getByRole("menuitem", { name: /Langue/ }).click();
      const picker = page.getByTestId("language-dialog");
      await picker.getByRole("combobox").fill("English");
      await picker.getByRole("option", { name: /^English/ }).click();

      await expect(page.getByTestId("nav-environment")).toContainText("My environment");
    } finally {
      // Kept on the account: given back, for the specs after this one.
      accountLanguage("fr");
    }
  });
});
