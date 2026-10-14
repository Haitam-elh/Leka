import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * Intentions kept, in a real browser (LEKA-384).
 *
 * Asking LEKA keeps the intention — what was asked, by whom, where it
 * stands — with the context it asks for (LEKA-373). What a unit test cannot
 * answer: that asking from the composer reaches the database as an
 * intention, that Mes intentions and its page read it back, that its
 * history says what happened in order — LEKA's moves and the asker's —
 * and that cancelling it is kept.
 *
 * Other specs ask questions too: nothing here counts the list.
 */

test.describe("Intentions", () => {
  test("asked, kept, followed, its history told, cancelled", async ({ page }) => {
    await signIn(page);
    await page.goto("/intentions/new");
    await expect(page.getByRole("checkbox", { name: "acme/backend" })).toBeChecked();

    const asked = `Qui est responsable de payment-api ? (${Date.now()})`;
    await page.getByTestId("intention-input").fill(asked);
    await page.getByTestId("intention-submit").click();
    await page.getByTestId("intention-launch").click();
    await expect(page.getByTestId("intention-step-2")).toBeVisible();
    // Its scope (LEKA-386): no environment held — the demo's form chose
    // none, the words say none — and the period its kind's default.
    await expect(page.getByTestId("scope-environment")).toHaveText("Tous");
    await expect(page.getByTestId("scope-period")).toContainText(
      "par défaut pour ce type de demande",
    );

    // Kept: followed from Mes intentions.
    await page.getByTestId("intention-follow").click();
    await expect(page).toHaveURL(/\/intentions\/[0-9a-f-]{36}$/);
    // Opened at the step it is at (mockup 03): what was asked, above it.
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Analyse en cours");
    await expect(page.getByTestId("intention-step-badge")).toHaveText("Étape 2 sur 5");
    await expect(page.getByTestId("intention-step-analysis")).toHaveAttribute(
      "data-state",
      "current",
    );
    await expect(page.getByTestId("intention-status")).toContainText("Prête à analyser");
    await expect(page.getByTestId("intention-text")).toContainText(asked);
    // Step 1: what it is, and the context linked to it.
    await page.getByTestId("tab-overview").click();
    await expect(page).toHaveURL(/\/overview$/);
    await expect(page.getByTestId("intention-link").first()).toContainText("v1");

    // Its history: asked, its context linked, LEKA analysing.
    await page.getByTestId("tab-history").click();
    await expect(page).toHaveURL(/\/history$/);
    // What happened to the intention itself (its whole story: LEKA-392).
    await page.getByTestId("timeline-category-intention").click();
    const events = page.getByTestId("intention-event");
    await expect(events).toHaveCount(3);
    await expect(events.nth(0)).toContainText("Intention créée");
    await expect(events.nth(0)).toContainText("par vous");
    await expect(events.nth(2)).toContainText("LEKA a rassemblé le contexte");
    await expect(events.nth(2)).toContainText("par LEKA");

    // Cancelled by its asker, with a reason: said, and kept.
    await page.getByTestId("intention-cancel").click();
    const dialog = page.getByRole("alertdialog");
    await dialog.getByLabel("Raison (facultative)").fill("une question en double");
    await dialog.getByRole("button", { name: "Annuler l'intention" }).click();
    await expect(page.getByTestId("intention-status")).toContainText("Annulée");
    await expect(events).toHaveCount(4);
    await expect(events.nth(3)).toContainText("Raison : une question en double");

    // In Mes intentions, among the finished.
    await page.goto("/intentions");
    await page.getByTestId("intentions-tab-finished").click();
    const row = page.getByTestId("intention-row").filter({ hasText: asked });
    await expect(row).toBeVisible();
    await expect(row.getByTestId("intention-status")).toContainText("Annulée");
  });

  test("what a request lacks is asked before it is launched, answered, launched (LEKA-439)", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto("/intentions/new");
    await expect(page.getByRole("checkbox", { name: "acme/backend" })).toBeChecked();

    // An action on nothing named: LEKA asks on what — with why — and launches
    // nothing on a doubt.
    await page.getByTestId("intention-input").fill(`Redémarre le service (${Date.now()})`);
    await page.getByTestId("intention-submit").click();
    const question = page.locator(
      '[data-testid="brief-question"][data-kind="action_without_target"]',
    );
    await expect(question).toContainText("Sur quoi faut-il agir ?");
    await expect(question.getByTestId("brief-why")).toContainText(
      "doit savoir exactement ce qu'elle touche",
    );
    await expect(page.getByTestId("intention-launch")).toBeDisabled();

    // Answered in their words: read again, nothing left to ask.
    await question.getByTestId("brief-words").fill("payment-api");
    await question.getByTestId("brief-send").click();
    await expect(page.getByTestId("intention-brief")).toHaveAttribute("data-decision", "analyse");
    await expect(page.getByTestId("brief-answers")).toContainText("payment-api");
    await page.getByTestId("intention-launch").click();
    await expect(page.getByTestId("intention-step-2")).toBeVisible();

    await page.getByTestId("intention-follow").click();
    await expect(page.getByTestId("intention-status")).toContainText("Prête à analyser");
    // Its answer kept with it.
    await page.getByTestId("tab-overview").click();
    await expect(page.getByTestId("brief-answers")).toContainText("payment-api");
  });

  test("waiting for an answer, it is answered on its page (LEKA-439)", async ({ page }) => {
    await signIn(page);
    // Asked elsewhere — the API — without what it acts on: it waits.
    const csrf = (await page.context().cookies()).find((c) => c.name === "leka_csrf")?.value ?? "";
    const response = await page.request.post("http://localhost:8000/api/v1/intentions", {
      data: { text: `Redémarre le service (${Date.now()})` },
      headers: { "X-CSRF-Token": csrf },
    });
    expect(response.ok()).toBe(true);
    const { intention } = (await response.json()) as { intention: { id: string; status: string } };
    expect(intention.status).toBe("needs_clarification");

    await page.goto(`/intentions/${intention.id}/overview`);
    await expect(page.getByTestId("intention-status")).toContainText("Clarification requise");
    const question = page.locator(
      '[data-testid="brief-question"][data-kind="action_without_target"]',
    );
    await question.getByTestId("brief-words").fill("payment-api");
    await question.getByTestId("brief-send").click();
    await expect(page.getByTestId("intention-status")).toContainText("Prête à analyser");
    await page.getByTestId("tab-history").click();
    await page.getByTestId("timeline-category-intention").click();
    await expect(page.getByTestId("intention-event").last()).toContainText("Précisée");
  });
});
