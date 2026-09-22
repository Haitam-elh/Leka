import { expect, test, type Page } from "@playwright/test";

/**
 * The shell, in a real browser, at the sizes it claims to support.
 *
 * Three things a unit test cannot answer: that the frame is the same on
 * every route, that it reshapes itself at each breakpoint rather than
 * overflowing, and that the skip link actually moves focus.
 *
 * Uses the demo account from `python scripts/seed.py`, like the sign-in
 * journey beside it.
 */

const DEMO_EMAIL = "nora@acme.example";
const DEMO_PASSWORD = "leka-demo-password";

/** The viewports the ticket supports: laptop, small desktop, desktop. */
const SIZES = [
  { name: "1440", width: 1440, height: 900, sidebar: "visible" },
  { name: "1280", width: 1280, height: 800, sidebar: "visible" },
  { name: "1024", width: 1024, height: 768, sidebar: "visible" },
] as const;

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(DEMO_EMAIL);
  await page.getByLabel("Password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL("http://localhost:3000/");
}

test.describe("the shell", () => {
  test("is the same frame on every area of the product", async ({ page }) => {
    await signIn(page);

    for (const [href, id] of [
      ["/", "overview"],
      ["/intentions", "intentions"],
      ["/sources", "sources"],
      ["/team", "team"],
    ] as const) {
      await page.goto(href);

      await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
      await expect(page.getByTestId("user-menu").first()).toBeVisible();
      await expect(page.locator("main#main-content")).toBeVisible();
      // The entry for the page you are on, and only that one.
      await expect(page.locator('a[aria-current="page"]')).toHaveCount(1);
      await expect(page.getByTestId(`nav-${id}`)).toHaveAttribute("aria-current", "page");
    }
  });

  for (const size of SIZES) {
    test(`fits at ${size.name}px without a horizontal scrollbar`, async ({ page }) => {
      await page.setViewportSize({ width: size.width, height: size.height });
      await signIn(page);

      await expect(page.getByRole("navigation", { name: "Main navigation" })).toBeVisible();

      // Nothing sticks out sideways: the one thing a shell gets wrong first.
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(0);

      // The content scrolls, the frame does not.
      await expect(page.locator("header")).toBeVisible();
      await expect(page.locator("main#main-content")).toBeVisible();
    });
  }

  test("folds to a rail and remembers it across a reload", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await signIn(page);

    const toggle = page.getByTestId("sidebar-toggle");
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect(page.getByTestId("nav-sources")).toContainText("Sources");

    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");

    await page.reload();
    await expect(page.getByTestId("sidebar-toggle")).toHaveAttribute("aria-expanded", "false");
  });

  test("hides the sidebar behind a button below 1024px, and Escape closes it", async ({ page }) => {
    await signIn(page);
    await page.setViewportSize({ width: 900, height: 800 });

    const navigation = page.getByRole("navigation", { name: "Main navigation" });
    await expect(navigation).toBeHidden();

    await page.getByTestId("open-navigation").click();
    await expect(navigation).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(navigation).toBeHidden();
  });

  test("lets the keyboard skip the twelve navigation links", async ({ page }) => {
    await signIn(page);

    const skip = page.getByRole("link", { name: "Skip to content" });

    // Not "the first Tab": `next dev` injects its own dev-tools button into
    // the page, and it takes a tab stop that production does not have. What
    // matters is that the skip link comes BEFORE the navigation, so a few
    // presses are allowed — but reaching a navigation link first is the
    // failure this test is about.
    for (let press = 0; press < 3; press += 1) {
      await page.keyboard.press("Tab");
      if (await skip.evaluate((node) => node === document.activeElement)) break;

      const onANavigationLink = await page.evaluate(
        () => document.activeElement?.closest("nav[aria-label]") !== null,
      );
      expect(onANavigationLink, "the navigation was reached before the skip link").toBe(false);
    }

    await expect(skip).toBeFocused();

    await page.keyboard.press("Enter");
    await expect(page.locator("main#main-content")).toBeFocused();
  });

  test("changes language from the account menu", async ({ page }) => {
    await signIn(page);

    await expect(page.getByTestId("nav-environment")).toContainText("My environment");

    await page.getByTestId("user-menu").last().click();
    await page.getByRole("menuitemradio", { name: "Français" }).click();

    await expect(page.getByTestId("nav-environment")).toContainText("Mon environnement");
  });
});
