import { expect, type Page, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * « Mon environnement », understood (LEKA-532), in a real browser against
 * the real API and the demo company.
 *
 * What a unit test cannot answer: that the home's « N éléments inconnus »
 * opens exactly those N things; that the score, the counts, the figures at
 * the top and the rows of the diagnosis say the same numbers; that every
 * cloud resource on the map has a state from the six, said on hover with
 * why and when; that a resource chosen on the map says its state and where
 * each of its links comes from; that it all holds on a phone.
 */

const SIX = ["unavailable", "degraded", "stale", "unknown", "not_covered", "operational"];

async function percent(page: Page, testid: string): Promise<number> {
  const said = (await page.getByTestId(testid).textContent()) ?? "";
  return Number(said.match(/(\d+)\s?%/)?.[1] ?? NaN);
}

test.describe("Mon environnement, understood", () => {
  test.use({ viewport: { width: 1536, height: 1100 } });

  test("the home's unknown things open as exactly those, each with why and what to do", async ({ page }) => {
    await signIn(page);
    await page.goto("/overview");
    const link = page.getByTestId("home-unknown");
    const count = Number(((await link.textContent()) ?? "").match(/\d+/)?.[0]);
    expect(count).toBeGreaterThan(0);
    await link.click();
    await expect(page).toHaveURL(/\/environment\?state=unknown$/);
    await expect(page.getByTestId("diagnostic-filter")).toContainText(`Seulement « Inconnu » : ${count}`);
    const rows = page.getByTestId("diagnostic").getByRole("table").getByRole("row");
    await expect(rows).toHaveCount(count + 1);
    for (const state of await page.getByTestId("diagnostic-state").all()) {
      await expect(state).toHaveAttribute("data-state", "unknown");
    }
    // Each says why from what its sources say, and what would fix it.
    for (const why of await page.getByTestId("diagnostic-why").all()) {
      expect(((await why.textContent()) ?? "").length).toBeGreaterThan(20);
    }
    await expect(page.getByTestId("diagnostic-fix")).toHaveCount(count);
    // « Inconnu » defined apart from « Non couvert ».
    await expect(page.getByTestId("diagnostic-filter")).toContainText("Inconnu ne veut dire ni sain, ni en panne.");
  });

  test("the score, the counts, the figures and the rows say the same numbers", async ({ page }) => {
    await signIn(page);
    await page.goto("/environment");
    const ring = await percent(page, "overall-share");
    const counts = page.getByTestId("overall").getByTestId("twin-counts");
    let total = 0;
    let unknown = 0;
    for (const state of SIX) {
      const said = (await counts.locator(`[data-state="${state}"]`).textContent()) ?? "";
      const n = Number(said.match(/\d+/)?.[0] ?? 0);
      total += n;
      if (state === "unknown") unknown = n;
    }
    // The figures at the top: the same share of « Inconnu ».
    await expect(page.getByTestId("arch-figure-health")).toContainText(
      `${Math.round((100 * unknown) / total)} %`,
    );
    await page.getByTestId("overall-diagnose").click();
    await expect(page.getByTestId("diagnostic")).toBeVisible();
    expect(await percent(page, "diagnostic-health")).toBe(ring);
    const notHealthy = await page.getByTestId("diagnostic").getByRole("table").getByRole("row").count();
    const healthy = Number(
      ((await page.getByTestId("diagnostic-health").textContent()) ?? "").match(/(\d+) sur/)?.[1],
    );
    expect(notHealthy - 1 + healthy).toBe(total);
  });

  test("every cloud resource on the map has one of the six states, said on hover, and explained when chosen", async ({ page }) => {
    await signIn(page);
    await page.goto("/environment");
    const dots = page.getByTestId("status-dot");
    await expect(dots.first()).toBeVisible();
    for (const dot of await dots.all()) {
      expect(SIX).toContain(await dot.getAttribute("data-state"));
      expect(await dot.getAttribute("title")).toMatch(/observé|jamais observé/);
    }
    await page.getByRole("button", { name: /ecs-prod-cluster/ }).first().click();
    const panel = page.getByTestId("architecture-panel");
    await expect(panel.getByTestId("architecture-state-why")).toContainText("observé");
    await panel.getByTestId("architecture-panel-relations").click();
    const origins = panel.getByTestId("relation-origin");
    await expect(origins.first()).toBeVisible();
    for (const origin of await origins.all()) {
      await expect(origin).toHaveText(/^(observé|déduit) : .+/);
    }
    // Its state's diagnosis, one click away.
    await panel.getByRole("link", { name: "Pourquoi cet état" }).click();
    await expect(page.getByTestId("diagnostic")).toBeVisible();
  });
});

test.describe("The diagnosis on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("nothing wider than the screen: the table scrolls in its own frame", async ({ page }) => {
    await signIn(page);
    await page.goto("/environment?state=unknown");
    await expect(page.getByTestId("diagnostic")).toBeVisible();
    expect(
      await page.evaluate(() => {
        const main = document.querySelector("#main-content") as HTMLElement;
        return main.scrollWidth - main.clientWidth;
      }),
    ).toBeLessThanOrEqual(0);
  });
});
