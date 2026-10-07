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
    await expect(page.getByRole("heading", { level: 1 })).toContainText(asked);
    await expect(page.getByTestId("intention-status")).toContainText("En analyse");
    await expect(page.getByTestId("intention-text")).toContainText(asked);
    await expect(page.getByTestId("intention-link").first()).toContainText("v1");

    // Its history: asked, its context linked, LEKA analysing.
    await page.getByTestId("tab-history").click();
    await expect(page).toHaveURL(/\/history$/);
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

  test("not understood enough, it is asked, then clarified (LEKA-385)", async ({ page }) => {
    await signIn(page);
    await page.goto("/intentions/new");
    await expect(page.getByRole("checkbox", { name: "acme/backend" })).toBeChecked();

    // An action on nothing named: LEKA asks on what.
    await page.getByTestId("intention-input").fill("Redémarre le service");
    await page.getByTestId("intention-submit").click();
    await expect(page.getByTestId("intention-step-2")).toBeVisible();
    await expect(page.getByTestId("understanding-needs")).toContainText(
      "LEKA a besoin d'une précision",
    );
    await expect(
      page.locator('[data-testid="understanding-question"][data-kind="action_without_target"]'),
    ).toContainText("Sur quoi faut-il agir ?");

    await page.getByTestId("intention-follow").click();
    await expect(page.getByTestId("intention-status")).toContainText("À préciser");
    await expect(page.getByTestId("understanding-action").first()).toContainText(
      "validation requise",
    );

    // Clarified: the same intention, its words said better.
    await page.getByTestId("understanding-clarify").click();
    await expect(page).toHaveURL(/\/intentions\/new\?intention=/);
    const input = page.getByTestId("intention-input");
    await expect(input).toHaveValue("Redémarre le service");
    await input.fill("Redémarre payment-api");
    await page.getByTestId("intention-submit").click();
    await expect(page.getByTestId("intention-step-2")).toBeVisible();
    await expect(page.getByTestId("understanding-needs")).toHaveCount(0);
    await expect(page.getByTestId("understanding-goal")).toContainText("Agir");

    await page.getByTestId("intention-follow").click();
    await expect(page.getByTestId("intention-status")).toContainText("En analyse");
    await page.getByTestId("tab-history").click();
    await expect(page.getByTestId("intention-event").last()).toContainText("Précisée");
  });
});
