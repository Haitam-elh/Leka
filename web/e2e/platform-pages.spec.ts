import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * The pages that showed nothing, in a real browser: Mon Dashboard's state
 * of the environment; an entity's tabs — metrics, deployments, log,
 * configuration — from what its sources show; Équipe & accès — who is in,
 * an invitation made, its link, revoked; Facturation — the consumption.
 */

const API = "http://localhost:8000/api/v1";

test.describe("Platform pages", () => {
  test("the dashboard says the environment's state", async ({ page }) => {
    await signIn(page);
    await page.goto("/overview");
    for (const kpi of ["kpi-services", "kpi-attention", "kpi-incidents"]) {
      await expect(page.getByTestId(kpi)).not.toHaveText("—");
      await expect(page.getByTestId(kpi)).toHaveText(/^\d+$/);
    }
  });

  test("an entity's tabs say what its sources show", async ({ page }) => {
    await signIn(page);
    const environment = await (await page.request.get(`${API}/ingestion/enrichment/environment`)).json();
    const node =
      environment.nodes.find((n: { type: string; entity_id: string | null }) => n.type === "service" && n.entity_id) ??
      environment.nodes.find((n: { entity_id: string | null }) => n.entity_id);
    expect(node).toBeTruthy();
    const segment = node.type === "service" ? "services" : node.type === "repository" ? "repositories" : "databases";
    const base = `/environment/${segment}/${node.entity_id}`;

    await page.goto(`${base}/metrics`);
    await expect(page.getByTestId("metrics-tab")).toBeVisible();
    await expect(page.getByTestId("activity-changes")).toContainText(/\d/);
    await page.goto(`${base}/deployments`);
    await expect(page.getByTestId("deployments").or(page.getByTestId("deployments-empty"))).toBeVisible();
    await page.goto(`${base}/logs`);
    await expect(page.getByTestId("logs-filter-all")).toBeVisible();
    await page.goto(`${base}/configuration`);
    await expect(page.getByTestId("configuration-tab")).toBeVisible();
  });

  test("the team: who is in, an invitation made and revoked", async ({ page }) => {
    await signIn(page);
    await page.goto("/team");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Votre équipe");
    await expect(page.getByTestId("team-member").first()).toContainText("@");

    const address = `invite-${Date.now()}@acme.example`;
    await page.getByTestId("team-invite-open").click();
    await page.getByTestId("invite-email").fill(address);
    await page.getByTestId("invite-send").click();
    await expect(page.getByTestId("invite-link")).toContainText("/invitations/");

    await page.getByTestId("team-tab-invitations").click();
    const invitation = page.getByTestId("team-invitation").filter({ hasText: address });
    await expect(invitation).toBeVisible();
    await invitation.getByTestId("team-revoke").click();
    await expect(invitation).toHaveCount(0);
  });

  test("billing says the consumption", async ({ page }) => {
    await signIn(page);
    await page.goto("/billing");
    await expect(page.getByTestId("billing-plan")).toContainText("Aucune offre payante active");
    await expect(page.getByTestId("billing-entities")).toContainText(/\d/);
  });
});
