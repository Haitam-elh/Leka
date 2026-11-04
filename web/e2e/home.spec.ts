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
 * - The hero simplified (LEKA-528): the title on one line on a laptop, its
 *   « ? » never alone on a phone; no subtitle; the field's text in the
 *   middle of the field, of its spark and its buttons. Each agent's card
 *   one target: clicked anywhere, or reached by the keyboard, it opens the
 *   agent's page — no description, no button of its own.
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

/** The lines a node's text is laid on, by their tops — of one of its
 * children when `child` is given. */
const linesOf = (page: Page, selector: string, child?: number) =>
  page.evaluate(
    ([selector, child]) => {
      const found = document.querySelector(selector as string);
      if (!found) throw new Error(`${selector} not found`);
      const node = child === undefined ? found : found.childNodes[child as number];
      const range = document.createRange();
      range.selectNodeContents(node);
      return new Set([...range.getClientRects()].map((rect) => Math.round(rect.top))).size;
    },
    [selector, child] as const,
  );

/** Where the field's first line sits, and the middles of the field, its
 * spark and its button. */
const centres = (page: Page) =>
  page.evaluate(() => {
    const field = document.querySelector('[data-testid="intention-input"]') as HTMLElement;
    const row = field.parentElement as HTMLElement;
    const style = getComputedStyle(field);
    const box = field.getBoundingClientRect();
    const middle = (el: Element) => {
      const r = el.getBoundingClientRect();
      return r.top + r.height / 2;
    };
    return {
      line: box.top + parseFloat(style.paddingTop) + parseFloat(style.lineHeight) / 2,
      // Above and below its text, the same: the text's block in its middle.
      even: style.paddingTop === style.paddingBottom,
      field: middle(field),
      spark: middle(row.firstElementChild as Element),
      submit: middle(row.querySelector('[data-testid="intention-submit"]') as Element),
    };
  });

for (const width of [1280, 1440, 1536]) {
  test.describe(`The hero at ${width} px (LEKA-528)`, () => {
    test.use({ viewport: { width, height: 900 } });

    test("the title on one line, no subtitle, the field's text in its middle", async ({ page }) => {
      await home(page);
      await expect(page.locator("#compact-composer-title")).toHaveText("Que souhaitez\u2011vous accomplir ?");
      expect(await linesOf(page, "#compact-composer-title")).toBe(1);
      await expect(page.getByText(/Posez votre question, lancez une analyse/)).toHaveCount(0);
      const at = await centres(page);
      for (const other of [at.field, at.spark, at.submit]) expect(Math.abs(at.line - other)).toBeLessThanOrEqual(1);
    });
  });
}

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

  test("no example, no bundle banner, one link to the agents and bundles; one row of agents, the bundles, the latest", async ({ page }) => {
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
    // Those its columns hold: the rest are hidden, never on a second row.
    for (const card of await cards.filter({ visible: true }).all()) {
      // Its state in words, always; a price only where there is one to pay.
      await expect(card.getByTestId("agent-state")).toBeVisible();
    }
    // Measured at once, the page settled: nothing loading above moves some
    // cards between two readings.
    const tops = await cards.evaluateAll((all) =>
      all
        .filter((card) => (card as HTMLElement).offsetParent !== null)
        .map((card) => Math.round(card.getBoundingClientRect().top)),
    );
    // One row (LEKA-488): every card on the same line.
    expect(tops.length).toBeLessThanOrEqual(6);
    expect(tops.filter((top) => top === tops[0])).toHaveLength(tops.length);
    await expect(page.getByTestId("home-bundles-cards").getByTestId("bundle").first()).toBeVisible();
    // The bundles right after the agents, the latest analyses after them.
    const agents = await box(page, "home-agents");
    const bundles = await box(page, "home-bundles-cards");
    expect(bundles.y).toBeGreaterThan(agents.y + agents.height - 1);
    if (await page.getByTestId("home-latest").count()) {
      const latest = await box(page, "home-latest");
      expect(latest.y).toBeGreaterThan(bundles.y + bundles.height - 1);
    }
  });

  test("an agent's card is one target: clicked anywhere, or by the keyboard, it opens its page (LEKA-528)", async ({ page }) => {
    await home(page);
    const grid = page.getByTestId("home-agents-grid");
    const first = page.getByTestId("home-agent").filter({ visible: true }).first();
    const key = await first.getAttribute("data-key");
    await expect(first.getByTestId("agent-state")).toBeVisible();
    // Its domain, its name, its state: no description, no generic line, no button.
    await expect(first.getByRole("link")).toHaveCount(1);
    await expect(first.getByRole("button")).toHaveCount(0);
    for (const gone of ["Fonctionne avec vos sources connectées", "Ouvrir l'agent", "Acheter l'agent", "Voir les options"]) {
      await expect(grid.getByText(gone)).toHaveCount(0);
    }
    // The keyboard reaches it right after « Voir tous les agents et bundles », the card says so.
    const ring = () => first.evaluate((card) => getComputedStyle(card).boxShadow);
    const resting = await ring();
    await page.getByRole("link", { name: "Voir tous les agents et bundles" }).focus();
    await page.keyboard.press("Tab");
    await expect(first.getByTestId("home-agent-open")).toBeFocused();
    expect(await ring()).not.toBe(resting);
    // Clicked by its lower corner, far from its title: its page.
    const at = await first.boundingBox();
    if (!at) throw new Error("no card");
    await first.click({ position: { x: 12, y: at.height - 10 } });
    await expect(page).toHaveURL(new RegExp(`/capabilities/${key}$`));
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
    // The title wraps on a phone: « Que souhaitez-vous », never cut at its
    // hyphen, then « accomplir ? », its « ? » with its word (LEKA-528).
    expect(await linesOf(page, "#compact-composer-title")).toBe(2);
    expect(await linesOf(page, "#compact-composer-title", 0)).toBe(1);
    expect(await linesOf(page, "#compact-composer-title span")).toBe(1);
    // The placeholder takes lines here: their block in the field's middle,
    // level with the spark and the button.
    const at = await centres(page);
    expect(at.even).toBe(true);
    for (const other of [at.spark, at.submit]) expect(Math.abs(at.field - other)).toBeLessThanOrEqual(1);

    const cards = await page.getByTestId("home-agent").filter({ visible: true }).all();
    // One row: two on a phone (LEKA-488).
    expect(cards.length).toBeLessThanOrEqual(2);
    if (cards.length >= 2) {
      const [first, second] = await Promise.all(cards.slice(0, 2).map((card) => card.boundingBox()));
      expect(Math.round(first?.y ?? 0)).toBe(Math.round(second?.y ?? 1));
    }
  });
});
