import { expect, type Page, test } from "@playwright/test";

import { analyse, ask, openStep } from "./intention-helpers";
import { signIn } from "./sign-in";

/**
 * Decisions on intentions, in a real browser (LEKA-390).
 *
 * What a unit test cannot answer: that an action asked from the composer,
 * once analysed, waits in À valider with its risk and what it needs under
 * the workspace's policy; that who may approve approves it there — asked
 * first — and the intention is approved, the vote kept; that it can be
 * refused from the intention's own page, saying why, and nothing more is
 * asked of anyone.
 *
 * The demo's policy is LEKA's default: a medium risk — a restart in
 * production — wants one approval, which its asker may give. Each test
 * decides what it asked: nothing is left waiting.
 */

const API = "http://localhost:8000/api/v1";

async function decisionOf(page: Page, intentionId: string): Promise<string> {
  const response = await page.request.get(`${API}/intentions/${intentionId}/decisions`);
  expect(response.ok()).toBe(true);
  const [latest] = (await response.json()) as { id: string }[];
  return latest.id;
}

test.describe("Intention decisions", () => {
  test("an action asked waits in À valider, and is approved there", async ({ page }) => {
    await signIn(page);
    const id = await ask(page, `Redémarre auth-service en production (${Date.now()})`);
    analyse(id);

    await page.goto(`/approvals/${await decisionOf(page, id)}?kind=decision`);
    const panel = page.getByTestId("decision-panel");
    await expect(panel).toContainText("Redémarre auth-service en production");
    await expect(panel.getByTestId("decision-status")).toHaveText("À valider");
    await expect(panel.getByTestId("decision-risk")).toHaveText("Risque moyen");
    await expect(panel.getByTestId("decision-requirement")).toHaveText(
      "1 validation requise · 0 sur 1",
    );
    const proposal = panel.getByTestId("decision-proposal");
    await expect(proposal).toContainText("Redémarrer");
    await expect(proposal).toContainText("auth-service");
    await expect(proposal).toContainText("en production");
    await expect(proposal).toContainText("Réversible");

    await panel.getByTestId("decision-approve").click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("Redémarrer · auth-service · production");
    await dialog.getByRole("button", { name: "Valider" }).click();
    // Decided: no longer waiting.
    await expect(panel).toHaveCount(0);

    // Approved, it is at its action; what was decided, step 4.
    await page.goto(`/intentions/${id}/overview`);
    await expect(page.getByTestId("intention-step-action")).toHaveAttribute("data-state", "current");
    await openStep(page, "decision");
    await expect(page.getByTestId("intention-status")).toContainText("Approuvée");
    const decision = page.getByTestId("decision");
    await expect(decision.getByTestId("decision-status")).toHaveText("Validée");
    await expect(decision.getByTestId("decision-vote")).toContainText("Validée par vous");
    await expect(decision.getByTestId("decision-actions")).toHaveCount(0);

    await openStep(page, "history");
    // What happened to the intention itself (its whole story: LEKA-392).
    await page.getByTestId("timeline-category-intention").click();
    await expect(page.getByTestId("intention-event").last()).toContainText("Approuvée");
  });

  test("refused from the intention's page, saying why", async ({ page }) => {
    await signIn(page);
    const id = await ask(page, `Redémarre auth-service en production (${Date.now()})`);
    analyse(id);
    // The decision step's own view.
    await page.goto(`/intentions/${id}/decision`);

    const decision = page.getByTestId("decision");
    await expect(decision.getByTestId("decision-status")).toHaveText("À valider");
    await decision.getByTestId("decision-reject").click();
    const dialog = page.getByRole("alertdialog");
    await dialog.getByRole("textbox").fill("Pas pendant les soldes.");
    await dialog.getByRole("button", { name: "Refuser" }).click();

    await expect(page.getByTestId("intention-status")).toContainText("Rejetée");
    await expect(decision.getByTestId("decision-status")).toHaveText("Refusée");
    const vote = decision.getByTestId("decision-vote");
    await expect(vote).toContainText("Refusée par vous");
    await expect(vote).toContainText("« Pas pendant les soldes. »");
  });
});
