import { expect, type Page, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * The keyboard pass of LEKA-438's checklist, on every page it redrew.
 *
 * What these protect: the first stops of the Tab key on each page land on
 * something visible that shows it has the focus — a ring, an outline —
 * never on nothing; and a detail panel beside a list closes on Escape, as
 * its ✕ does, from the moment the focus is inside it.
 */

const PAGES = [
  "/overview",
  "/intentions",
  "/approvals",
  "/sources",
  "/capabilities",
  "/governance",
  "/environment",
  "/activity",
  "/team",
  "/billing",
  "/settings",
];

const STOPS = 12;

/** What the focused element shows: an outline or a ring (a box-shadow). */
async function focusShown(page: Page): Promise<{ name: string; shown: boolean; visible: boolean }> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return { name: "body", shown: false, visible: false };
    const style = getComputedStyle(el);
    const box = el.getBoundingClientRect();
    const name = (el.getAttribute("aria-label") || el.textContent || el.tagName).trim().slice(0, 40);
    return {
      name,
      shown: (style.outlineStyle !== "none" && style.outlineWidth !== "0px") || style.boxShadow !== "none",
      visible: box.width > 0 && box.height > 0,
    };
  });
}

test.describe("the keyboard, page by page", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  for (const path of PAGES) {
    test(`${path}: each of the first stops shows its focus`, async ({ page }) => {
      await signIn(page);
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      const missing: string[] = [];
      for (let stop = 0; stop < STOPS; stop++) {
        await page.keyboard.press("Tab");
        const focus = await focusShown(page);
        if (!focus.visible || !focus.shown) missing.push(`${stop + 1}: ${focus.name}`);
      }
      // Named, so the failure says which stop shows nothing.
      expect(missing).toEqual([]);
    });
  }
});

test.describe("a detail panel closes on Escape", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("À valider: the decision opened on arrival", async ({ page }) => {
    await signIn(page);
    await page.goto("/approvals");
    const panel = page.locator("aside").filter({ has: page.getByRole("button", { name: /^Fermer/ }) }).first();
    await expect(panel).toBeVisible();
    await panel.getByRole("button", { name: /^Fermer/ }).focus();
    await page.keyboard.press("Escape");
    await expect(panel).toBeHidden();
  });

  test("Sources: the source in error opened on arrival", async ({ page }) => {
    await signIn(page);
    await page.goto("/sources");
    const panel = page.locator("aside").filter({ has: page.getByRole("button", { name: /^Fermer/ }) }).first();
    await expect(panel).toBeVisible();
    await panel.getByRole("button", { name: /^Fermer/ }).focus();
    await page.keyboard.press("Escape");
    await expect(panel).toBeHidden();
  });

  test("Mon environnement: the card chosen on the architecture", async ({ page }) => {
    await signIn(page);
    await page.goto("/environment");
    const close = page.getByRole("button", { name: /^Fermer/ }).first();
    await expect(close).toBeVisible();
    await close.focus();
    await page.keyboard.press("Escape");
    await expect(close).toBeHidden();
  });
});
