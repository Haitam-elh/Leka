import { expect, type Page, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * The bundles, navigable (LEKA-531), in a real browser against the real API.
 *
 * What a unit test cannot answer: that every bundle card, on the home and
 * in the marketplace, opens its own bundle's page when clicked anywhere — or
 * reached by the keyboard; that the page says the same price and the same
 * state as the card; that its agents each open their own page; that it
 * holds on a phone and a tablet, nothing wider than the screen, the way to
 * choose it on screen.
 */

type Card = { key: string; price: string; state: string | null };

async function cards(page: Page): Promise<Card[]> {
  const found = page.getByTestId("bundle");
  await expect(found.first()).toBeVisible();
  const said: Card[] = [];
  for (const card of await found.all()) {
    said.push({
      key: (await card.getAttribute("data-key")) ?? "",
      price: ((await card.getByTestId("bundle-price").textContent()) ?? "").trim(),
      state: await card.getAttribute("data-state"),
    });
  }
  return said;
}

async function opens(page: Page, from: string, card: Card): Promise<void> {
  await page.goto(from);
  const target = page.locator(`[data-testid="bundle"][data-key="${card.key}"]`);
  await target.scrollIntoViewIfNeeded();
  const box = await target.boundingBox();
  if (!box) throw new Error(`${card.key} not laid out`);
  // Clicked low on the card, far from its name: the whole card opens it.
  await target.click({ position: { x: box.width / 2, y: box.height - 40 } });
  await expect(page).toHaveURL(new RegExp(`/capabilities/bundles/${card.key}$`));
  const bundle = page.getByTestId("bundle-page");
  await expect(bundle).toHaveAttribute("data-key", card.key);
  // The same state, the same price, as on its card.
  await expect(bundle).toHaveAttribute("data-state", card.state ?? "");
  if (card.state !== "contract") {
    await expect(page.getByTestId("bundle-hero-price")).toContainText(card.price);
  }
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.getByTestId("bundle-agent").first()).toBeVisible();
}

test.describe("The bundles", () => {
  test.use({ viewport: { width: 1536, height: 1024 } });

  test("every card opens its own bundle's page, from the home and the marketplace", async ({ page }) => {
    await signIn(page);
    await page.goto("/overview");
    const home = await cards(page);
    expect(home.length).toBeGreaterThanOrEqual(5);
    for (const card of home) await opens(page, "/overview", card);

    await page.goto("/capabilities");
    const market = await cards(page);
    expect(market.map((c) => c.key)).toEqual(home.map((c) => c.key));
    for (const card of market) await opens(page, "/capabilities", card);
  });

  test("a bundle's page: its agents each to their page, the way back to the bundles", async ({ page }) => {
    await signIn(page);
    await page.goto("/overview");
    const [first] = await cards(page);
    await page.goto(`/capabilities/bundles/${first.key}`);
    const agent = page.getByTestId("bundle-agent").first();
    const key = await agent.getAttribute("data-key");
    await agent.click();
    await expect(page).toHaveURL(new RegExp(`/capabilities/${key}$`));
    await page.goBack();
    await page.getByTestId("bundle-back").click();
    await expect(page).toHaveURL(/\/capabilities#bundles$/);
    // Its tab says its name.
    await page.goto(`/capabilities/bundles/${first.key}`);
    const name = (await page.getByRole("heading", { level: 1 }).textContent())?.trim() ?? "";
    await expect(page).toHaveTitle(`${name} · LEKA`);
  });

  test("reached by the keyboard: the card says it, Enter opens it", async ({ page }) => {
    await signIn(page);
    await page.goto("/capabilities");
    const [first] = await cards(page);
    const card = page.locator(`[data-testid="bundle"][data-key="${first.key}"]`);
    const open = card.getByTestId("bundle-open");
    await open.focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    await expect(open).toBeFocused();
    expect(await card.evaluate((el) => getComputedStyle(el).boxShadow)).not.toBe("none");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(new RegExp(`/capabilities/bundles/${first.key}$`));
  });

  test("an unknown bundle says so, with the way back", async ({ page }) => {
    await signIn(page);
    await page.goto("/capabilities/bundles/nope");
    await expect(page.getByText("Ce bundle n'existe pas, ou n'est plus proposé.")).toBeVisible();
    await expect(page.getByTestId("bundle-back")).toBeVisible();
  });
});

for (const [name, width, height] of [
  ["phone", 390, 844],
  ["tablet", 820, 1180],
] as const) {
  test.describe(`A bundle's page on a ${name}`, () => {
    test.use({ viewport: { width, height } });

    test("nothing wider than the screen, the way to choose it on screen", async ({ page }) => {
      await signIn(page);
      await page.goto("/overview");
      const [first] = await cards(page);
      await page.goto(`/capabilities/bundles/${first.key}`);
      await expect(page.getByTestId("bundle-page")).toBeVisible();
      // The choice under the title, not in a column off screen.
      await expect(page.getByTestId("bundle-choose-top")).toBeVisible();
      await expect(page.getByTestId("bundle-choose")).toBeHidden();
      expect(
        await page.evaluate(() => {
          const main = document.querySelector("#main-content") as HTMLElement;
          return main.scrollWidth - main.clientWidth;
        }),
      ).toBeLessThanOrEqual(0);
    });
  });
}
