import { expect, type Locator, type Page, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * The pricing page (LEKA-431, LEKA-446), as a visitor reads it: every price from the
 * API — the catalogue's — the launch offer on monthly billing, the annual
 * discount on yearly, never both; Growth recommended; the Enterprise call
 * to action reaching the team; what the visitor chose counted. And every
 * page of the site leads to it, and says what the platform's plans say
 * (2026-11-04: they said two offers): the same prices, the same lines.
 *
 * In French: the site picks the browser's language.
 */
test.use({ locale: "fr-FR" });

test("the plans, monthly with the launch offer, yearly with the annual discount", async ({ page }) => {
  const events: string[] = [];
  page.on("request", (request) => {
    if (request.url().endsWith("/api/v1/pricing/events") && request.method() === "POST") {
      events.push(String(JSON.parse(request.postData() ?? "{}").event));
    }
  });
  await page.goto("/tarifs.html");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("capacité IA");

  const plans = page.locator("article.plan");
  await expect(plans).toHaveCount(5);
  await expect(plans.locator("h2")).toHaveText(["Free", "Starter", "Growth", "Business", "Enterprise"]);
  const growth = page.locator('article.plan[data-plan="growth"]');
  await expect(growth).toHaveClass(/plan--recommended/);
  await expect(growth).toContainText("Recommandé");

  // Monthly: the launch offer, its terms said.
  await expect(growth.locator(".plan__amount")).toHaveText("143,20 €");
  await expect(growth).toContainText("au lieu de 179 €");
  await expect(growth).toContainText("pendant 12 mois, puis 179 €");
  await expect(page.locator("#launchNote")).toBeVisible();
  await expect(page.locator("#launchTerms")).toContainText("Non cumulable avec la remise annuelle de 30 %");

  // Yearly: 30 % off, never the launch offer as well.
  await page.getByRole("radio", { name: /Annuel/ }).click();
  await expect(page.getByRole("radio", { name: /Annuel/ })).toHaveAttribute("aria-checked", "true");
  await expect(growth.locator(".plan__amount")).toHaveText("125,30 €");
  await expect(growth).toContainText("1 503,60 €");
  await expect(growth).not.toContainText("pendant 12 mois");
  await expect(page.locator("#launchNote")).toBeHidden();

  // AI capacity, Growth's trial, the own model on Enterprise only, no AI
  // capacity sold apart (LEKA-446). Metering's credits (LEKA-430), beside
  // the analyses they come to; the agents each plan includes (Karim,
  // 2026-10-15), and those sold apart as the marketplace prices them.
  await expect(growth).toContainText(/500 analyses standard équivalentes \/ mois \(10\s000 crédits IA\)/);
  await expect(growth).toContainText("8 agents spécialisés inclus");
  await expect(growth).toContainText("Essai gratuit de 14 jours, carte requise");
  await expect(page.locator('article.plan[data-plan="starter"]')).not.toContainText("Essai");
  await expect(page.locator('article.plan[data-plan="free"]')).not.toContainText("agents");
  await expect(page.locator("#trialTerms")).toContainText("sauf annulation avant la fin de l'essai");
  await expect(page.locator("#addOnsText")).toContainText(
    "3 avec Starter, 8 avec Growth, 12 avec Business, tous avec Enterprise",
  );
  await expect(page.locator("#addOnsText")).toContainText("de 9 € à 25 € par mois");
  await expect(page.locator("#addOnsText")).toContainText("jusqu'à 40 % moins cher");
  await expect(page.locator("main")).not.toContainText("Capacité IA supplémentaire");
  const enterprise = page.locator('article.plan[data-plan="enterprise"]');
  await expect(enterprise).toContainText("Sur devis");
  await expect(enterprise).toContainText("Connexion de votre propre LLM");
  await expect(growth).not.toContainText("propre LLM");

  // Enterprise: the team, through the enquiry form when no booking page is set.
  const reach = enterprise.locator(".plan__cta a").first();
  await expect(reach).toHaveAttribute("href", /demo\.html\?type=enterprise|^https:\/\//);

  // A self-service plan starts at sign-up, with what was chosen.
  await expect(growth.getByRole("link", { name: "Commencer" })).toHaveAttribute(
    "href",
    "/register?plan=growth&interval=year",
  );
  await expect.poll(() => events).toEqual(expect.arrayContaining(["page_viewed", "interval_selected"]));
});

/** A card's words, read alike on both pages: its lines, its tagline, its audience. */
async function said(card: Locator, lines: string, tagline: string, audience: string) {
  const plain = (text: string | null) => (text ?? "").replace(/\s+/g, " ").replace(/ ?\(/g, " (").trim();
  return {
    lines: (await card.locator(lines).allTextContents()).map(plain),
    tagline: plain(await card.locator(tagline).textContent()),
    audience: plain(await card.locator(audience).textContent()),
  };
}

/** Prices read alike: any space a plain one, Free's « Gratuit » the site's word for 0 €. */
const amounts = (all: string[]) => all.map((p) => p.replace(/\s+/g, " ").replace(/^Gratuit$/, "0 €"));

async function sitePrices(page: Page) {
  return amounts(await page.locator("article.plan .plan__amount").allTextContents());
}

test("the site's pricing says what the platform's plans say", async ({ page }) => {
  // The site first, as a visitor reads it.
  await page.goto("/tarifs.html");
  await expect(page.locator("article.plan")).toHaveCount(5);
  const site: Record<string, Awaited<ReturnType<typeof said>>> = {};
  for (const key of ["free", "starter", "growth", "business", "enterprise"]) {
    site[key] = await said(page.locator(`article.plan[data-plan="${key}"]`), ".plan__features li", ".plan__tagline", ".plan__audience");
  }
  const monthly = await sitePrices(page);
  await page.getByRole("radio", { name: /Annuel/ }).click();
  const yearly = await sitePrices(page);

  // Then the platform's plans, signed in: a workspace that may still have
  // the launch offer and Growth's trial, as a visitor would.
  await signIn(page);
  await page.goto("/billing/plans");
  const cards = page.getByTestId("plan-card");
  await expect(cards).toHaveCount(5);
  await expect(page.getByTestId("plans-launch-used")).toHaveCount(0);
  for (const key of Object.keys(site)) {
    const card = page.locator(`[data-testid="plan-card"][data-plan="${key}"]`);
    expect(await said(card, "ul li", '[data-testid="plan-tagline"]', '[data-testid="plan-audience"]'), key).toEqual(site[key]);
  }
  // The same prices, monthly then yearly.
  const prices = async () => amounts(await page.getByTestId("plan-price").allTextContents());
  expect(await prices()).toEqual(monthly);
  await page.getByTestId("plans-year").click();
  expect(await prices()).toEqual(yearly);
});

test("every page of the site leads to the pricing", async ({ page }) => {
  for (const address of ["/", "/connecteurs.html", "/demo.html"]) {
    await page.goto(address);
    await expect(page.locator('a[href="./tarifs.html"]').first()).toBeAttached();
  }
});

test("Facturation says when online payment is not open", async ({ page }) => {
  // No Stripe key here, as in CI: nothing can be bought, and it is said.
  await signIn(page);
  await page.goto("/billing");
  const section = page.getByTestId("billing-subscription");
  await expect(section).toContainText("Votre formule");
  await expect(section.getByTestId("billing-not-available")).toContainText("pas encore ouvert");
  await expect(section.getByRole("link", { name: "Voir les tarifs" })).toHaveAttribute("href", "/tarifs.html");
});
