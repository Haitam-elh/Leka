import { expect, test } from "@playwright/test";

import { LANDING, signIn } from "./sign-in";

/**
 * leka-core.com: Karim's site and the application, one address.
 *
 * The site is static files in public/; next.config.ts joins them to the
 * application with three rules. These walk what a visitor walks: the home
 * page, its "Se connecter", and back.
 *
 * In French: the site picks the browser's language, and Chromium here
 * would otherwise say English.
 */
test.use({ locale: "fr-FR" });

test("the home page is the site, and its sign-in is the application's", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveURL("http://localhost:3000/");
  await expect(page).toHaveTitle(/LEKA/);
  const signIn = page.locator("header").getByRole("link", { name: "Se connecter" });
  // Straight to the application's sign-in: not through /login.html, which a
  // browser may still hold from the old hosting as Karim's placeholder page.
  await expect(signIn).toHaveAttribute("href", "/login");
  await signIn.click();

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "Se connecter à LEKA" })).toBeVisible();
});

test("the site's own addresses lead where they should", async ({ page }) => {
  await page.goto("/index.html");
  await expect(page).toHaveURL("http://localhost:3000/");

  // The site's sign-in page could not sign anyone in; its address still
  // works, and lands on the one that can.
  await page.goto("/login.html");
  await expect(page).toHaveURL(/\/login$/);

  const connectors = await page.goto("/connecteurs.html");
  expect(connectors?.status()).toBe(200);
});

test("someone signed in follows the site's sign-in straight into the application", async ({
  page,
}) => {
  await signIn(page);

  await page.goto("/");
  await page.locator("header").getByRole("link", { name: "Se connecter" }).click();

  await expect(page).toHaveURL(LANDING);
});

test("the language chosen on the site carries into the application", async ({ page }) => {
  await page.goto("/");
  // What the site's language menu stores (public/i18n.js).
  await page.evaluate(() => window.localStorage.setItem("leka-lang", "en"));

  await page.goto("/login");

  await expect(page.getByRole("heading", { name: "Sign in to LEKA" })).toBeVisible();
});

test("on a phone, the site's sign-in is still there", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  const signIn = page.locator("header").getByRole("link", { name: "Se connecter" });
  await expect(signIn).toBeVisible();
  await signIn.click();

  await expect(page).toHaveURL(/\/login$/);
  // And the sign-in's own header keeps it too.
  await expect(page.locator("header").getByRole("link", { name: "Se connecter" })).toBeVisible();
});

test("the site's pages, its video and what search engines read all answer", async ({
  page,
  request,
}) => {
  for (const path of ["/a-propos.html", "/faq.html", "/connecteurs.html", "/documentation.html"]) {
    const answer = await request.get(path);
    expect(answer.status(), path).toBe(200);
  }
  const video = await request.get("/LEKA.mp4", { headers: { Range: "bytes=0-1023" } });
  expect([200, 206]).toContain(video.status());
  expect(await (await request.get("/robots.txt")).text()).toContain(
    "Sitemap: https://leka-core.com/sitemap.xml",
  );
  expect(await (await request.get("/sitemap.xml")).text()).toContain(
    "https://leka-core.com/faq.html",
  );

  // The header above the sign-in leads to the site's sections as they are now.
  await page.goto("/login");
  const nav = page.locator("header nav");
  await expect(nav.locator('a[href="/#environnement"]')).toBeVisible();
  await expect(nav.locator('a[href="/#controle"]')).toBeVisible();
});
