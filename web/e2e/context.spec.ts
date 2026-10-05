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
 * model makes no new version. Ranked (LEKA-372): what the demo's sources
 * disagree on — payment-api's SLA, GitHub's or Datadog's — is said with who
 * says what; the two accounts entity resolution found probably one person
 * are folded into one, their disagreement said; each element says why its
 * rank. Keeping up (LEKA-374): it says it is up to date with the model and
 * follows it; widened and narrowed, it makes new versions that say what of
 * the request changed, and each time is kept.
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
    // How it was searched: the graph from payment-api, the question's words.
    const searched = page.getByTestId("context-retrieval");
    await expect(searched).toContainText("Graphe");
    await expect(searched).toContainText("Recherche");

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

    // Archived: said, still read, never reassembled.
    await page.getByRole("button", { name: "Archiver" }).click();
    await expect(page.getByTestId("context-archived")).toBeVisible();
    await expect(page.getByRole("button", { name: "Réassembler" })).toHaveCount(0);
    await expect(page.getByTestId("context-elements")).toContainText("payment-api");
  });

  test("ranks what it gathered, folds the probable duplicates, says the conflicts", async ({
    page,
  }) => {
    await openContextTab(page);
    await page.getByLabel("Pourquoi ?").fill("Pourquoi payment-api est lent ?");
    await page.getByRole("button", { name: "Assembler le contexte" }).click();

    const elements = page.getByTestId("context-elements");
    const first = elements.getByTestId("context-element").first();
    await expect(first).toContainText("payment-api");
    await expect(first.getByTestId("element-disputed")).toBeVisible();

    const conflicts = page.getByTestId("context-conflicts");
    await expect(conflicts).toContainText("payment-api · sla");
    await expect(conflicts).toContainText("99.95 (retenu) · selon acme/backend");
    await expect(conflicts).toContainText("99.9 · selon acme-eu");
    await expect(conflicts).toContainText("Nadia Kowalski · email");

    // Jira's "Nadia K." is folded into Nadia Kowalski, said where it went.
    await expect(elements).toContainText("+1 doublon(s)");
    await expect(elements).not.toContainText("Nadia K.");
    const left = page.getByTestId("context-left-out");
    await left.getByRole("button", { name: "Voir la liste" }).click();
    await expect(left.getByTestId("left-out-list")).toContainText("Nadia K. · Doublon");
    await expect(left.getByTestId("left-out-list")).toContainText("doublon de Nadia Kowalski");

    // Opened: why that rank, signal by signal.
    await elements
      .getByRole("button", { name: "Provenance de payment-api", exact: true })
      .click();
    const why = page.getByTestId("element-ranking");
    await expect(why).toContainText("N° 1");
    await expect(why).toContainText("Demandé");
    await expect(why).toContainText("Cohérence");
  });

  test("keeps up: up to date, widened, narrowed, each version saying why", async ({ page }) => {
    await openContextTab(page);
    await page.getByLabel("Pourquoi ?").fill("Pourquoi payment-api est lent ?");
    await page.getByRole("button", { name: "Assembler le contexte" }).click();

    const freshness = page.getByTestId("context-freshness");
    await expect(freshness).toHaveAttribute("data-state", "fresh");
    await expect(freshness).toContainText("À jour avec le modèle de l'entreprise");
    await expect(page.getByTestId("context-following")).toContainText("Suit le modèle");
    await expect(freshness.getByRole("switch", { name: "Suivre le modèle" })).toBeChecked();

    const versions = page.getByTestId("context-versions").getByRole("listitem");
    await page.getByRole("button", { name: "Élargir" }).click();
    await expect(versions).toHaveCount(2);
    await expect(versions.first()).toContainText("v2 · élargie");
    await expect(versions.first()).toContainText(
      "portée (pas) : 1 → 2 · budget : 100 → 200 · période (jours) : 14 → 28",
    );

    await page.getByRole("button", { name: "Resserrer" }).click();
    await expect(versions).toHaveCount(3);
    await expect(versions.first()).toContainText("v3 · resserrée");
    await expect(versions.first()).toContainText("budget : 200 → 100");

    const checks = page.getByTestId("context-checks").getByRole("listitem");
    await expect(checks).toHaveCount(2);
    await expect(checks.first()).toContainText("Resserré");
    await expect(checks.first()).toContainText("version 3 créée");
  });
});
