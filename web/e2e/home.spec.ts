import { expect, type Page, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * The home, the question its focus (LEKA-470).
 *
 * What these protect:
 * - The question is the page's centre: centred in the content on a wide
 *   screen, « Mon environnement » reduced beside it, top right — its state
 *   and its last read, no counter of sources or services.
 * - « Historique des analyses », under the bar, opens the list of the
 *   intentions asked.
 * - No example of a question, no bundle banner: one link to the agents and
 *   the bundles, the bundles' own cards lower on the page (its mockup).
 * - The agents dense: six a row on a wide screen, two a row and six at
 *   most on a phone, nothing wider than the screen.
 */

async function home(page: Page) {
  await signIn(page);
  await page.goto("/overview");
  await expect(page.getByTestId("intention-input")).toBeVisible();
  await expect(page.getByTestId("home-health")).toBeVisible();
}

const box = async (page: Page, testId: string) => {
  const found = await page.getByTestId(testId).boundingBox();
  if (!found) throw new Error(`${testId} not laid out`);
  return found;
};

test.describe("The home on a wide screen", () => {
  test.use({ viewport: { width: 1536, height: 1024 } });

  test("the question centred, « Mon environnement » reduced top right", async ({ page }) => {
    await home(page);
    const main = await box(page, "home-focus");
    const content = await page.locator("#main-content").boundingBox();
    if (!content) throw new Error("no main content");
    // Centred in the page's content, within a few pixels (the scrollbar).
    expect(Math.abs(main.x + main.width / 2 - (content.x + content.width / 2))).toBeLessThan(12);
    const env = await box(page, "home-environment");
    expect(env.x).toBeGreaterThan(main.x + main.width);
    expect(Math.abs(env.y - main.y)).toBeLessThan(40);

    const card = page.getByTestId("home-environment");
    await expect(card).not.toContainText(/sources? connectées?/i);
    await expect(card).not.toContainText(/services analysés/i);
    // The last read, the real one: a moment the API gave, or said none.
    const sync = page.getByTestId("home-last-sync");
    await expect(sync).toContainText("Dernière synchronisation");
    const time = sync.locator("time");
    if (await time.count()) {
      const at = await time.getAttribute("datetime");
      expect(Number.isNaN(Date.parse(at ?? ""))).toBe(false);
    } else {
      await expect(sync).toContainText("Aucune source lue pour l'instant");
    }
  });

  test("no example, no bundle banner, one link to the agents and bundles; six agents a row", async ({ page }) => {
    await home(page);
    for (const example of ["Analyser un incident récent", "Comprendre un changement", "Préparer un plan de migration"]) {
      await expect(page.getByRole("button", { name: example })).toHaveCount(0);
    }
    await expect(page.getByTestId("first-steps-examples")).toHaveCount(0);
    await expect(page.getByTestId("home-bundles")).toHaveCount(0);
    await expect(page.getByText("Découvrir les bundles")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Voir tous les agents et bundles" })).toHaveCount(1);

    const cards = page.getByTestId("home-agent");
    await expect(cards.first()).toBeVisible();
    const tops: number[] = [];
    for (const card of await cards.all()) {
      tops.push(Math.round((await card.boundingBox())?.y ?? -1));
      // Its state in words, always; a price only where there is one to pay.
      await expect(card.getByTestId("agent-state")).toBeVisible();
    }
    expect(tops.length).toBeLessThanOrEqual(12);
    expect(tops.filter((top) => top === tops[0])).toHaveLength(Math.min(6, tops.length));
    await expect(page.getByTestId("home-bundles-cards").getByTestId("bundle").first()).toBeVisible();
  });

  test("« Historique des analyses » opens the intentions asked", async ({ page }) => {
    await home(page);
    await page.getByRole("link", { name: "Historique des analyses" }).click();
    await expect(page).toHaveURL(/\/intentions$/);
  });
});

test.describe("The home on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the question first, nothing wider than the screen, two agents a row", async ({ page }) => {
    await home(page);
    const main = await box(page, "home-focus");
    const env = await box(page, "home-environment");
    expect(env.y).toBeGreaterThan(main.y + main.height - 1);
    expect(
      await page.evaluate(() => {
        const content = document.querySelector("#main-content") as HTMLElement;
        return content.scrollWidth - content.clientWidth;
      }),
    ).toBeLessThanOrEqual(0);
    await expect(page.getByRole("link", { name: "Historique des analyses" })).toBeVisible();

    const cards = await page.getByTestId("home-agent").filter({ visible: true }).all();
    expect(cards.length).toBeLessThanOrEqual(6);
    if (cards.length >= 2) {
      const [first, second] = await Promise.all(cards.slice(0, 2).map((card) => card.boundingBox()));
      expect(Math.round(first?.y ?? 0)).toBe(Math.round(second?.y ?? 1));
    }
  });
});
