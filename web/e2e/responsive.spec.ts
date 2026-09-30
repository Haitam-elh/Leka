import { expect, type Page, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * The core screens at every size LEKA supports: laptop to large desktop.
 *
 * shell.spec.ts checks the frame. This checks what goes in it, which is
 * where the defects actually were: at 1024px, with the rail, the composer's
 * "⌘↵ pour lancer" broke over three lines and a panel's link left its
 * question mark alone on one. Nothing overflowed — which is why a check for
 * overflow alone passed them.
 *
 * Below 1024px is out of scope: the product is used at a desk. The shell
 * still folds into a drawer there (shell.spec.ts), so it is usable, not
 * designed for.
 */

const WIDTHS = [1024, 1280, 1440, 1920] as const;

/** Each screen, and the one control that must be usable on it. */
const SCREENS: readonly [path: string, primary: (page: Page) => ReturnType<Page["getByRole"]>][] = [
  ["/overview", (page) => page.getByRole("button", { name: "Lancer l'analyse" })],
  ["/intentions/new", (page) => page.getByRole("button", { name: "Lancer l'analyse" })],
  ["/intentions/new?step=decision", (page) => page.getByRole("checkbox").first()],
  ["/settings", (page) => page.getByRole("button", { name: "Enregistrer" })],
  ["/sources", (page) => page.getByRole("heading", { level: 1 })],
  ["/environment", (page) => page.getByRole("button", { name: "Entreprise" })],
];

for (const width of WIDTHS) {
  test(`the core screens are whole at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await signIn(page);

    for (const [path, primary] of SCREENS) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 }), path).toBeVisible();

      // Nothing sideways, in the page or in the scrolling content.
      const overflow = await page.evaluate(() => {
        const main = document.querySelector("main");
        return Math.max(
          document.documentElement.scrollWidth - document.documentElement.clientWidth,
          main ? main.scrollWidth - main.clientWidth : 0,
        );
      });
      expect(overflow, `${path} overflows at ${width}px`).toBeLessThanOrEqual(0);

      // The primary control is on screen, not clipped past its right edge.
      const control = primary(page);
      await expect(control, path).toBeVisible();
      const box = await control.boundingBox();
      expect(box, path).not.toBeNull();
      expect(box!.x + box!.width, `${path} at ${width}px`).toBeLessThanOrEqual(width);
    }
  });
}

test("the composer's hints stay on one line at the narrowest size", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 800 });
  await signIn(page);
  await page.goto("/intentions/new");

  for (const text of ["⌘↵ pour lancer", "0 / 2000"]) {
    const box = await page.getByText(text, { exact: true }).boundingBox();
    expect(box, text).not.toBeNull();
    // One line of 12px text is about 16px tall; the regression was 48.
    expect(box!.height, `"${text}" wraps`).toBeLessThan(24);
  }
});
