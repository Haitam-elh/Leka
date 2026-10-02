import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * The knowledge graph, explored end to end (LEKA-369): the screens ask the
 * API, the API asks PostgreSQL, on the demo company of scripts/seed.py.
 *
 * What a unit test cannot answer: that a search finds what the seed wrote
 * — its words folded at the seed as a build folds them — that a walk and a
 * shortest way come back from the database, and that the canvas says them
 * in words.
 */

test.describe("the detailed map", () => {
  test("draws the dependencies, then walks around what is searched", async ({ page }) => {
    await signIn(page);
    await page.goto("/environment");
    await page.getByRole("link", { name: /Voir la cartographie détaillée/ }).click();

    await expect(page).toHaveURL(/\/environment\/graph$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Cartographie détaillée");
    const words = page.getByTestId("graph-text");
    await expect(words).toContainText("payment-api dépend de postgres-prod");

    // Centred on what is searched: what surrounds it, one step away. The
    // service first among the five things "paym" finds — its incident, its
    // deployment, its runbook after it.
    await page.getByTestId("explorer-focus").getByRole("combobox").fill("paym");
    const service = page.getByRole("option", { name: "payment-api Service", exact: true });
    await expect(service).toHaveAttribute("aria-selected", "true");
    await service.click();
    await expect(page).toHaveURL(/\/environment\/graph\?entity=/);
    await expect(page.getByTestId("explorer-selected")).toContainText("Point de départ");
    await expect(words).toContainText("payment-api dépend de auth-service");
    await expect(words).toContainText("payment-api est déployé sur ecs-prod-cluster");

    // And how it is tied to anything else.
    await page.getByTestId("explorer-path").getByRole("combobox").fill("ecs");
    await page.getByRole("option", { name: /^ecs-prod-cluster/ }).click();
    const way = page.getByTestId("explorer-path-result");
    await expect(way).toContainText("1 pas");
    await expect(way.getByRole("link", { name: "ecs-prod-cluster" })).toBeVisible();
  });
});

test.describe("the palette's search", () => {
  test("finds what the company model knows, and goes to it", async ({ page }) => {
    await signIn(page);

    await page.keyboard.press("ControlOrMeta+k");
    await page.getByTestId("palette-input").fill("postgres");

    const found = page.getByRole("option", { name: /^postgres-prod/ });
    await expect(found).toBeVisible();
    await found.click();
    await expect(page).toHaveURL(/\/environment\/databases\/[0-9a-f-]{36}$/);
  });
});
