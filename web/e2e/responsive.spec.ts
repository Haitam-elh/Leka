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
 * And on a tablet and a phone (2026-10-27): every screen within the
 * screen's width, nothing pushed past its edge — the steps of an intention
 * all on screen, the site's header whole before signing in.
 */

const WIDTHS = [1024, 1280, 1440, 1920] as const;

/** Each screen, and the one control that must be usable on it. */
const SCREENS: readonly [path: string, primary: (page: Page) => ReturnType<Page["getByRole"]>][] = [
  ["/overview", (page) => page.getByRole("button", { name: "Lancer l'analyse" })],
  // What LEKA understood comes first (LEKA-439): « Continuer », then launched.
  ["/intentions/new", (page) => page.getByRole("button", { name: "Continuer" })],
  ["/intentions/new?step=decision", (page) => page.getByRole("checkbox").first()],
  ["/settings", (page) => page.getByRole("button", { name: "Enregistrer" })],
  ["/sources", (page) => page.getByRole("heading", { level: 1 })],
  // Its views' tab bar — not the detail panel's own tabs.
  [
    "/environment",
    (page) =>
      page.getByRole("tablist", { name: "Vue de l'environnement" }).getByRole("tab", { name: "Vue d'ensemble" }),
  ],
  ["/environment/graph", (page) => page.getByRole("combobox", { name: "Centrer sur" })],
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

/** The screens a phone and a tablet open, each whole within their width. */
const SMALL = [390, 768] as const;
const EVERY = [
  "/overview",
  "/intentions",
  "/intentions/new",
  "/environment",
  "/environment/graph",
  "/sources",
  "/capabilities",
  "/activity",
  "/approvals",
  "/architecte",
  "/billing",
  "/billing/plans",
  "/governance",
  "/notifications",
  "/settings",
  "/team",
] as const;

/** How far the page, or anything in it outside a scroller, passes the right edge. */
async function pastTheEdge(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const scrolled = (element: Element): boolean => {
      for (let at = element.parentElement; at && at !== document.body; at = at.parentElement) {
        if (getComputedStyle(at).overflowX !== "visible") return true;
      }
      return false;
    };
    const past = Array.from(document.querySelectorAll("main *, header *"))
      .filter((element) => {
        const box = element.getBoundingClientRect();
        return box.width > 0 && box.right > width + 1 && !scrolled(element);
      })
      .map((element) => `${element.tagName.toLowerCase()} «${(element.textContent ?? "").trim().slice(0, 40)}»`);
    if (document.documentElement.scrollWidth > width) past.unshift(`the page, by ${document.documentElement.scrollWidth - width}px`);
    return past.slice(0, 5);
  });
}

for (const width of SMALL) {
  test(`every screen is whole on a ${width}px screen`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await signIn(page);
    for (const path of EVERY) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 }), path).toBeVisible();
      expect(await pastTheEdge(page), `${path} at ${width}px`).toEqual([]);
    }
    // The five steps of an intention, every one on screen.
    await page.goto("/intentions/new");
    for (const step of ["intention", "analysis", "results", "decision", "action"]) {
      const box = await page.getByTestId(`intention-step-${step}`).boundingBox();
      expect(box, step).not.toBeNull();
      expect(box!.x + box!.width, `${step} at ${width}px`).toBeLessThanOrEqual(width);
    }
  });
}

test("the site's header is whole before signing in, from a phone to a laptop", async ({ page }) => {
  for (const width of [390, 768, 1024, 1280]) {
    await page.setViewportSize({ width, height: 800 });
    for (const path of ["/login", "/register"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      expect(await pastTheEdge(page), `${path} at ${width}px`).toEqual([]);
    }
  }
});
