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

  test("Agents: each domain's box the same size as those beside it (2026-10-25)", async ({ page }) => {
    await signIn(page);
    await page.goto("/capabilities");
    // The agents' boxes (LEKA-467: LEKA's skills are a section of their own).
    const agents = page.locator('[data-testid="catalogue-domain"][data-kind="agent"]');
    await expect(agents.nth(2)).toBeVisible();
    const boxes = await agents.evaluateAll((all) =>
      all.map((box) => {
        const r = box.getBoundingClientRect();
        return { top: Math.round(r.top), height: Math.round(r.height), width: Math.round(r.width) };
      }),
    );
    // Side by side, three a row; every box the same size, closed.
    const rows = new Map<number, { height: number; width: number }[]>();
    for (const box of boxes) rows.set(box.top, [...(rows.get(box.top) ?? []), box]);
    expect(rows.size).toBeLessThan(boxes.length);
    for (const box of boxes) {
      expect(Math.abs(box.height - boxes[0].height)).toBeLessThanOrEqual(1);
      expect(Math.abs(box.width - boxes[0].width)).toBeLessThanOrEqual(1);
    }
  });

  test("a page at rest asks the API again at the calm pace, never faster", async ({ page }) => {
    // 2026-10-29 (« que rien ne soit statique »): every page reads again
    // every LIVE_EVERY (web/lib/live.ts, 10 s) while it is in view — never
    // at the pace of something at work (3 to 5 s). Watched a little less
    // than that pace: each address asked again once at most.
    // Five pages watched 9 s each: about a minute alone — past the default
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
      await page.waitForTimeout(9_000);
      page.off("request", count);
      // Nothing is working on anything here: nothing followed fast.
      const times = new Map<string, number>();
      for (const url of again) times.set(url, (times.get(url) ?? 0) + 1);
      const fast = [...times].filter(([, n]) => n > 1).map(([url]) => url);
      expect(fast, `${path} kept asking: ${fast.join(", ")}`).toHaveLength(0);
    }
  });
});
