import { expect, test } from "@playwright/test";

import { analyse, ask, settleAll } from "./intention-helpers";
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
 * - Capacités: each domain's box sits right under the one before it in its
 *   column — no white band down to the next row (2026-10-14).
 * - A page at rest asks the API nothing more: nothing read again in a loop
 *   (2026-10-14: « l'affichage a pris un net retard »).
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

  test("Capacités: each domain's box right under the one before, in four columns (LEKA-460)", async ({ page }) => {
    await signIn(page);
    await page.goto("/capabilities");
    // The agents' boxes (LEKA-467: LEKA's skills are a section of their own).
    const agents = page.locator('[data-testid="catalogue-domain"][data-kind="agent"]');
    await expect(agents.nth(2)).toBeVisible();
    const boxes = await agents.evaluateAll((all) =>
      all.map((box) => {
        const r = box.getBoundingClientRect();
        return { left: Math.round(r.left), top: r.top, bottom: r.bottom };
      }),
    );
    const columns = new Map<number, { top: number; bottom: number }[]>();
    for (const box of boxes) columns.set(box.left, [...(columns.get(box.left) ?? []), box]);
    expect(columns.size).toBe(4);
    for (const column of columns.values()) {
      column.sort((a, b) => a.top - b.top);
      for (let i = 1; i < column.length; i++) {
        // The 16px between two boxes, never more.
        expect(column[i].top - column[i - 1].bottom).toBeLessThanOrEqual(17);
      }
    }
  });

  test("a page at rest asks the API nothing more", async ({ page }) => {
    // Five pages watched 10 s each: about a minute alone — past the default
    // 60 s on a slow runner (CI, 2026-10-15).
    test.setTimeout(180_000);
    await signIn(page);
    const id = await ask(page, `Qui est responsable d'auth-service ? (${Date.now()})`);
    analyse(id);
    // What earlier specs asked and left waiting is genuinely followed — a
    // list read again every 15 s, which a slow runner sees inside the
    // window: settled first, as the sweep would.
    settleAll();
    for (const path of ["/overview", "/intentions", "/capabilities", "/environment", `/intentions/${id}/results`]) {
      // Every call from the moment it is opened: a first load can end late
      // on a slow runner — what is checked is a call made AGAIN.
      const loaded = new Set<string>();
      const load = (request: { url: () => string }) => {
        if (request.url().includes("/api/v1/")) loaded.add(request.url());
      };
      page.on("request", load);
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      const again: string[] = [];
      const seen = new Set<string>();
      const count = (request: { url: () => string }) => {
        const url = request.url();
        if (!url.includes("/api/v1/")) return;
        if (loaded.has(url) || seen.has(url)) again.push(url);
        seen.add(url);
      };
      page.off("request", load);
      page.on("request", count);
      await page.waitForTimeout(10_000);
      page.off("request", count);
      // Nothing is working on anything here: nothing to follow.
      expect(again, `${path} kept asking: ${again.join(", ")}`).toHaveLength(0);
    }
  });
});
