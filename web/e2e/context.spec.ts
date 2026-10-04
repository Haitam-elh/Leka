import { expect, test } from "@playwright/test";

import { openContextTab } from "./context-tab";

/**
 * The context engine, end to end (LEKA-370): the screen asks the API, the
 * API reads the company model of scripts/seed.py in PostgreSQL, assembles
 * and keeps a version.
 *
 * What a unit test cannot answer: that a context is assembled from what the
 * database holds — payment-api first, what it depends on after it — that
 * each element opens on where it came from, and that reassembling the same
 * model makes no new version.
 */

test.describe("the context engine", () => {
  test("assembles around an entity, says where each came from", async ({ page }) => {
    await openContextTab(page);
    await page.getByLabel("Pourquoi ?").fill("Pourquoi payment-api est lent ?");
    await page.getByRole("button", { name: "Assembler le contexte" }).click();

    const elements = page.getByTestId("context-elements");
    await expect(elements.getByTestId("context-element").first()).toContainText("payment-api");
    await expect(elements.getByTestId("context-element").first()).toContainText(
      "Point de départ",
    );
    await expect(elements).toContainText("payment-api dépend de auth-service");
    await expect(page.getByTestId("context-version-line")).toContainText("Version 1");

    // Opened: why it is there, where it came from, what LEKA reads of it.
    await elements
      .getByRole("button", { name: "Provenance de payment-api", exact: true })
      .click();
    const provenance = page.getByTestId("context-provenance");
    await expect(provenance).toContainText("Point de départ");
    await expect(provenance).toContainText('service "payment-api"');

    // Reassembled from the same model: nothing changed, no new version.
    await page.getByRole("button", { name: "Réassembler" }).click();
    await expect(page.getByText("Rien n'a changé : la version 1 tient toujours.")).toBeVisible();
    await expect(page.getByTestId("context-versions").getByRole("listitem")).toHaveCount(1);
  });
});
