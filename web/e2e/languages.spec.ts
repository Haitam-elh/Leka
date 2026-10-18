import { expect, type Page, test } from "@playwright/test";

import { accountLanguage } from "./account-language";
import { DEMO_EMAIL, DEMO_PASSWORD, expectShellReady, expectSignedIn, LANDING, loginAnswer, signIn } from "./sign-in";

/**
 * Languages, end to end (docs/languages.md).
 *
 * A first visit reads the browser's language, on the site and the sign-in
 * alike, and never the country over it; a language LEKA does not offer
 * falls back to English; the picker offers the catalogue's 140, found by
 * their own names; a choice made before signing in follows the person into
 * the application and onto their account — every device after it; the
 * layout mirrors right to left and survives longer words.
 *
 * The browser in the other specs speaks French (playwright.config.ts).
 * Each test here says its own, and the demo account is given back French.
 */

/** A browser whose only language is one LEKA does not offer. */
async function speaking(page: Page, tags: string[]): Promise<void> {
  await page.addInitScript((said) => {
    Object.defineProperty(navigator, "languages", { get: () => said });
    Object.defineProperty(navigator, "language", { get: () => said[0] });
  }, tags);
}

const html = (page: Page) => page.locator("html");

test.afterEach(() => accountLanguage("fr"));

test.describe("a first visit, in German", () => {
  test.use({ locale: "de-DE" });

  test("reads the site in German, and the sign-in in English meanwhile", async ({ page }) => {
    await page.goto("/");
    await expect(html(page)).toHaveAttribute("lang", "de");

    await page.goto("/login");
    // German is offered, not yet translated in the application: English,
    // said as such — the chosen language stays German.
    await expect(html(page)).toHaveAttribute("data-language", "de");
    await expect(html(page)).toHaveAttribute("lang", "en");
    await expect(page.getByRole("heading", { name: "Sign in to LEKA" })).toBeVisible();
  });
});

test("the first paint is already in the right language, from the server", async ({ request }) => {
  const body = await (await request.get("/login", { headers: { "Accept-Language": "ja-JP,ja;q=0.9" } })).text();
  expect(body).toMatch(/<html[^>]*lang="en"/);
  expect(body).toMatch(/<html[^>]*data-language="ja"/);
});

test.describe("a browser language LEKA does not offer", () => {
  test.use({ extraHTTPHeaders: { "Accept-Language": "tlh" } });

  test("falls back to English", async ({ page }) => {
    await speaking(page, ["tlh"]);
    await page.goto("/login");
    await expect(html(page)).toHaveAttribute("data-language", "en");
    await expect(page.getByRole("heading", { name: "Sign in to LEKA" })).toBeVisible();
    await page.goto("/");
    await expect(html(page)).toHaveAttribute("lang", "en");
  });
});

test.describe("a country, as a hint", () => {
  test.use({ extraHTTPHeaders: { "Accept-Language": "tlh", "cf-ipcountry": "FR" } });

  test("chooses only when the browser says nothing LEKA offers", async ({ page }) => {
    await speaking(page, ["tlh"]);
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Se connecter à LEKA" })).toBeVisible();
  });
});

test.describe("a browser in English, in France", () => {
  test.use({ locale: "en-US", extraHTTPHeaders: { "cf-ipcountry": "FR" } });

  test("reads English: the country never wins over the browser", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Sign in to LEKA" })).toBeVisible();
  });
});

test("the picker offers the 140 languages, searched by their own names", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("language-button").click();
  const dialog = page.getByTestId("language-dialog");
  await expect(dialog.getByRole("option")).toHaveCount(140);

  // Every script draws, and each name is in its own language.
  for (const [tag, name] of [
    ["ja", "日本語"],
    ["ar", "العربية الفصحى"],
    ["hi", "हिन्दी"],
    ["ru", "Русский"],
    ["th", "ไทย"],
    ["ko", "한국어"],
    ["he", "עברית"],
    ["am", "አማርኛ"],
  ]) {
    const option = dialog.locator(`[data-tag="${tag}"] [lang="${tag}"]`);
    await expect(option).toHaveText(name);
    expect((await option.boundingBox())?.width ?? 0).toBeGreaterThan(0);
  }

  await dialog.getByRole("combobox").fill("日本");
  await expect(dialog.getByRole("option")).toHaveCount(1);
  await dialog.getByRole("combobox").fill("japonais");
  await expect(dialog.locator('[data-tag="ja"]')).toBeVisible();
  await dialog.getByRole("combobox").fill("turkce");
  await expect(dialog.locator('[data-tag="tr"]')).toBeVisible();
});

test("a choice made before signing in follows the person, and every device after", async ({ page, browser }) => {
  accountLanguage(null);
  await page.goto("/");
  // On the site, as a visitor: English.
  await page.locator(".lang-select").first().selectOption("en");
  await expect(html(page)).toHaveAttribute("lang", "en");

  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Sign in to LEKA" })).toBeVisible();
  await page.getByLabel("Email", { exact: true }).fill(DEMO_EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(DEMO_PASSWORD);
  const answered = loginAnswer(page);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  expectSignedIn(await answered);
  await expect(page).toHaveURL(LANDING);
  await expectShellReady(page);
  await expect(html(page)).toHaveAttribute("lang", "en");

  // Another device, which never chose: the account's English.
  const other = await browser.newContext({ locale: "fr-FR" });
  const elsewhere = await other.newPage();
  await signIn(elsewhere);
  await expect(elsewhere.locator("html")).toHaveAttribute("lang", "en");
  await other.close();
});

test("someone whose account has no language is asked once, and keeps it", async ({ page }) => {
  accountLanguage(null);
  await signIn(page);
  const notice = page.getByTestId("language-notice");
  await expect(notice).toContainText("LEKA s'affiche en Français, la langue de votre navigateur.");
  await notice.getByRole("button", { name: "Garder" }).click();
  await expect(notice).toBeHidden();
  await page.reload();
  await expectShellReady(page);
  await expect(page.getByTestId("language-notice")).toBeHidden();
});

test("the account menu and the settings change the language and the region", async ({ page }) => {
  await signIn(page);
  await page.getByTestId("user-menu").last().click();
  await page.getByTestId("language").click();
  const dialog = page.getByTestId("language-dialog");
  await dialog.getByRole("combobox").fill("english");
  await dialog.locator('[data-tag="en"]').click();
  await expect(page.getByTestId("nav-environment")).toContainText("My environment");

  await page.goto("/settings");
  const settings = page.getByTestId("language-settings");
  await expect(settings.getByTestId("language-current")).toHaveText("English");
  // The region writes the date its way; the words stay English.
  await expect(settings).toContainText(/Example: \d{1,2} [A-Z][a-z]+ \d{4}/);
  await settings.getByTestId("region").selectOption("US");
  await expect(settings).toContainText(/Example: [A-Z][a-z]+ \d{1,2}, \d{4}/);
  await expect(settings.getByTestId("language-current")).toHaveText("English");
});

test.describe("right to left", () => {
  for (const width of [1280, 1440]) {
    test(`the layout mirrors and stays whole at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await signIn(page);
      for (const where of ["/overview", "/settings", "/sources", "/intentions/new"]) {
        await page.goto(`${where}${where.includes("?") ? "&" : "?"}qa-language=ar-XB`);
        await expect(html(page)).toHaveAttribute("dir", "rtl");
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        // The logo, the header's start, on the right.
        const logo = await page.getByTestId("home-logo").boundingBox();
        expect(logo && logo.x > width / 2, where).toBe(true);
        const sideways = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect(sideways, where).toBeLessThanOrEqual(0);
      }
      // A form and a dialog, mirrored: the picker's search is on the right.
      await page.getByTestId("user-menu").last().click();
      await page.getByTestId("language").click();
      await expect(page.getByTestId("language-dialog")).toBeVisible();
      await page.goto("/overview?qa-language=");
    });
  }
});

test("longer words, as German or Finnish will be, leave every screen whole", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await signIn(page);
  for (const where of ["/overview", "/settings", "/sources", "/intentions/new", "/billing"]) {
    await page.goto(`${where}?qa-language=en-XA`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const sideways = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(sideways, where).toBeLessThanOrEqual(0);
  }
  await page.goto("/overview?qa-language=");
});

test("an answer in Arabic reads right to left inside a French screen", async ({ page }) => {
  await signIn(page);
  await page.goto("/intentions/new");
  const input = page.getByTestId("intention-input");
  await input.fill("لماذا تطبيق الدفع بطيء منذ الأمس؟");
  const direction = await input.evaluate((element) => getComputedStyle(element).unicodeBidi);
  expect(direction).toBe("plaintext");
});
