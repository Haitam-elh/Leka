import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * The pricing page (LEKA-431), as a visitor reads it: every price from the
 * API — the catalogue's — the launch offer on monthly billing, the annual
 * discount on yearly, never both; Growth recommended; the Enterprise call
 * to action reaching the team; what the visitor chose counted. And every
 * page of the site leads to it.
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
  await expect(growth.locator(".plan__amount")).toHaveText("125,30 €");
  await expect(growth).toContainText("au lieu de 179 €");
  await expect(growth).toContainText("pendant 12 mois, puis 179 €");
  await expect(page.locator("#launchNote")).toBeVisible();
  await expect(page.locator("#launchTerms")).toContainText("Non cumulable avec la remise annuelle de 20 %");

  // Yearly: 20 % off, never the launch offer as well.
  await page.getByRole("radio", { name: /Annuel/ }).click();
  await expect(page.getByRole("radio", { name: /Annuel/ })).toHaveAttribute("aria-checked", "true");
  await expect(growth.locator(".plan__amount")).toHaveText("143,20 €");
  await expect(growth).toContainText("1 718,40 €");
  await expect(growth).not.toContainText("pendant 12 mois");
  await expect(page.locator("#launchNote")).toBeHidden();

  // AI capacity, the core agents, the own model on Enterprise only.
  // Metering's credits (LEKA-430), as the page reads them from it.
  await expect(growth).toContainText("10 000 crédits IA / mois");
  await expect(growth).toContainText("Architecte applicatif et QA — analyse des tests inclus");
  const enterprise = page.locator('article.plan[data-plan="enterprise"]');
  await expect(enterprise).toContainText("Sur devis");
  await expect(enterprise).toContainText("Connexion de votre propre modèle de langage");
  await expect(growth).not.toContainText("propre modèle");

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
