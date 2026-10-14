import { expect, test } from "@playwright/test";

import { analyse, ask } from "./intention-helpers";
import { signIn } from "./sign-in";

/**
 * The frame every page sits in, at a laptop's size (2026-10-14).
 *
 * What these protect:
 * - Scrolled down and up, again and again, the content scrolls and the frame
 *   never does: no white band at the bottom, the header and the sidebar
 *   always in place. What a page positions absolutely — a label only screen
 *   readers read — once made the document taller than the window.
 * - The step open on an intention's page is ringed whole: its ring is not
 *   cut by the strip that scrolls the steps sideways.
 */

test.use({ viewport: { width: 1451, height: 754 } });

test.describe("The frame", () => {
  test("scrolled down and up again and again, only the content moves", async ({ page }) => {
    await signIn(page);
    const id = await ask(page, `Qui est responsable d'auth-service ? (${Date.now()})`);
    analyse(id);
    await page.goto(`/intentions/${id}/results`);
    await expect(page.getByTestId("intention-results")).toBeVisible();

    const frame = () =>
      page.evaluate(() => ({
        document: document.scrollingElement?.scrollTop ?? 0,
        tall: (document.scrollingElement?.scrollHeight ?? 0) - window.innerHeight,
        main: (document.querySelector("#main-content") as HTMLElement).scrollTop,
      }));
    expect((await frame()).tall).toBeLessThanOrEqual(0);
    for (const where of [{ x: 900, y: 500 }, { x: 120, y: 500 }]) {
      await page.mouse.move(where.x, where.y);
      for (let round = 0; round < 4; round++) {
        for (const delta of [400, -400]) {
          for (let k = 0; k < 8; k++) await page.mouse.wheel(0, delta);
          await page.waitForTimeout(150);
          expect((await frame()).document).toBe(0);
        }
      }
    }
    // The content did scroll.
    await page.mouse.move(900, 500);
    for (let k = 0; k < 8; k++) await page.mouse.wheel(0, 400);
    await expect.poll(async () => (await frame()).main).toBeGreaterThan(0);
    await expect(page.getByRole("banner")).toBeInViewport();
  });

  test("the step open is ringed whole", async ({ page }) => {
    await signIn(page);
    const id = await ask(page, `Qui est responsable d'auth-service ? (${Date.now()})`);
    analyse(id);
    await page.goto(`/intentions/${id}/results`);
    const strip = page.getByTestId("intention-stepper");
    const step = page.getByTestId("intention-step-results");
    await expect(step).toBeVisible();
    const room = await page.evaluate(() => {
      const strip = document.querySelector('[data-testid="intention-stepper"]') as HTMLElement;
      const disc = document.querySelector(
        '[data-testid="intention-step-results"] [aria-hidden="true"].rounded-full',
      ) as HTMLElement;
      const a = strip.getBoundingClientRect();
      const b = disc.getBoundingClientRect();
      return { top: b.top - a.top, bottom: a.bottom - b.bottom };
    });
    // Its ring (2px) and the current step's halo (6px) fit inside the strip.
    expect(room.top).toBeGreaterThanOrEqual(6);
    await expect(strip).toBeVisible();
  });
});
