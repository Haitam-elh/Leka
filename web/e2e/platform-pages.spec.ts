import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * The pages that showed nothing, in a real browser: Vue d'ensemble's state
 * of the environment, as the Digital Twin says it (LEKA-442); an entity's tabs — metrics, deployments, log,
 * configuration — from what its sources show; Équipe & accès — who is in,
 * an invitation made, its link, revoked; Facturation — the consumption.
 */

const API = "http://localhost:8000/api/v1";

test.describe("Platform pages", () => {
  test("the dashboard says the environment's state", async ({ page }) => {
    await signIn(page);
    // What the twin says (LEKA-442) — the overview says the same.
    const environment = await (await page.request.get(`${API}/ingestion/enrichment/environment`)).json();
    const troubled = environment.nodes.filter(
      (n: { twin: { state: string } | null }) => n.twin && ["unavailable", "degraded"].includes(n.twin.state),
    );
    await page.goto("/overview");
    // Since the home's redesign (#469), what is wrong sits in the ribbon
    // under the composer — two at most, each in its state, the way to
    // analyse it — and the greeting says how the environment is.
    const trouble = page.getByTestId("ribbon-trouble");
    if (troubled.length) {
      await expect(trouble).toHaveCount(Math.min(troubled.length, 2));
      for (const state of await trouble.evaluateAll((all) => all.map((el) => el.getAttribute("data-state")))) {
        expect(["unavailable", "degraded"]).toContain(state);
      }
      await expect(trouble.first().getByRole("link", { name: "Analyser" })).toHaveAttribute(
        "href",
        /^\/intentions\/new\?q=/,
      );
      await expect(page.getByTestId("greeting-chapeau")).toContainText("en difficulté");
    } else {
      await expect(trouble).toHaveCount(0);
    }
    // The tiles that said nothing to act on are gone.
    await expect(page.getByTestId("kpi-services")).toHaveCount(0);
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
    await expect(page.getByTestId("billing-plan")).toContainText("Business");
    await expect(page.getByTestId("billing-credits")).toContainText("Crédits IA du mois");
    await expect(page.getByTestId("billing-entities")).toContainText(/\d/);
  });
});
