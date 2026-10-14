import { expect, test } from "@playwright/test";

import { analyse } from "./intention-helpers";
import { signIn } from "./sign-in";

/**
 * The new interface, at /v2, in a real browser (2026-10-14, the product
 * call's Lot 6).
 *
 * What a unit test cannot answer: that /v2 is its own frame — no sidebar,
 * no dashboard — beside the current interface, on the same session; that
 * the environment's health and LEKA's sources come from the demo's twin;
 * that the demo workspace's agents are a click away under the bar; that
 * what is typed there is asked — nothing to launch, nothing to follow — and
 * answered under it, as LEKA analyses it; and that Historique opens it
 * again.
 *
 * There is no worker here: the analysis the API queues is run as the job
 * runner would, for this intention only.
 */

test.describe("The new interface", () => {
  test("one bar, its agents, the environment's health; asked, answered under the bar", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto("/v2");

    // Its own frame: no sidebar, no dashboard.
    await expect(page.getByTestId("v2-shell")).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Navigation principale" })).toHaveCount(0);
    await expect(page.getByTestId("overview-now")).toHaveCount(0);

    // The environment's health, top right, opened on its sources.
    const health = page.getByTestId("v2-health");
    await expect(health).toHaveAttribute("data-health", /^(stable|attention|incident)$/);
    await health.click();
    await expect(page.getByTestId("v2-environment-source").first()).toBeVisible();
    await page.keyboard.press("Escape");

    // LEKA tied to the sources it reads; the agents under the bar.
    await expect(page.getByTestId("v2-constellation-source").first()).toBeVisible();
    await page.getByTestId("v2-agent-chip").filter({ hasText: /^\/architecte$/ }).click();
    await expect(page.getByTestId("v2-ask")).toHaveValue(/^\/architecte /);

    // Asked: nothing to launch, nothing to follow — its exchange opens.
    const asked = `Qui est responsable de auth-service ? (${Date.now()})`;
    await page.getByTestId("v2-ask").fill(asked);
    await page.getByTestId("v2-ask").press("Enter");
    await expect(page).toHaveURL(/\/v2\?i=[0-9a-f-]{36}$/);
    const id = new URL(page.url()).searchParams.get("i") ?? "";
    await expect(page.getByTestId("v2-said")).toContainText(asked);
    await expect(page.getByTestId("v2-reading")).toBeVisible();

    analyse(id);

    // Answered under the bar, read again while LEKA works: then its decision.
    await expect(page.getByTestId("analysis-summary")).toContainText(
      "auth-service appartient à Thomas Berger.",
      { timeout: 20_000 },
    );
    await expect(page.getByTestId("v2-thread")).toHaveAttribute("data-state", "decision_required");
    await expect(page.getByTestId("v2-detail")).toHaveAttribute("href", `/intentions/${id}`);

    // Historique, from the avatar's menu: opened again, the same exchange.
    await page.getByTestId("v2-avatar").click();
    await page.getByTestId("v2-menu-history").click();
    await expect(page).toHaveURL(/\/v2\/history$/);
    await page.getByTestId("v2-history-row").filter({ hasText: asked }).click();
    await expect(page).toHaveURL(new RegExp(`/v2\\?i=${id}$`));
    await expect(page.getByTestId("v2-said")).toContainText(asked);
  });

  test("its second screen: the agents and their bundles, priced", async ({ page }) => {
    await signIn(page);
    await page.goto("/v2");
    await page.getByTestId("v2-see-all").click();

    await expect(page).toHaveURL(/\/v2\/agents$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Les compétences de LEKA");
    await expect(page.getByTestId("bundle")).toHaveCount(5);
    // « Demander » asks from the home's bar.
    await expect(page.getByTestId("catalogue-ask")).toHaveAttribute("href", "/v2");
  });

  test("leaves the current interface as it is, a click away", async ({ page }) => {
    await signIn(page);
    await page.goto("/v2");
    await page.getByTestId("v2-avatar").click();
    await page.getByTestId("v2-menu-classic").click();

    await expect(page).toHaveURL(/\/overview$/);
    await expect(page.getByRole("navigation", { name: "Navigation principale" })).toBeVisible();
  });
});
