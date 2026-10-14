import { expect, type Page, test } from "@playwright/test";

import { analyse, approved, ask } from "./intention-helpers";
import { signIn } from "./sign-in";

/**
 * One intention, one state, on every screen (LEKA-443) — in a real
 * browser, against the API. At each step, what the API says of it is read,
 * then compared with what each screen shows: the list, the panel beside it,
 * its page, its results, its history. A difference is a defect.
 *
 * The cases the ticket asks for:
 * - the same intention on the list, its page, its results, its history;
 * - changed after its analysis finished;
 * - stopped while it was being analysed;
 * - read again — a page refreshed, come back to later — while its actions
 *   run.
 * The others are proven by the API's tests (docs/intentions.md § 2 bis):
 * - a source failing during an analysis;
 * - several actions, part approved, refused;
 * - a run failed, timed out, retried, verified.
 */

const API = "http://localhost:8000/api/v1/intentions";

async function csrf(page: Page): Promise<string> {
  return (await page.context().cookies()).find((c) => c.name === "leka_csrf")?.value ?? "";
}

/** What the API says of it now. */
async function said(page: Page, id: string): Promise<{ state: string; reason: string | null }> {
  const response = await page.request.get(`${API}/${id}`);
  expect(response.ok()).toBe(true);
  const { journey } = (await response.json()) as {
    journey: { state: string; reason: string | null };
  };
  return journey;
}

/** Its state on its page, the list, the panel beside it — each the API's. */
async function everywhere(page: Page, id: string): Promise<string> {
  const { state } = await said(page, id);
  await page.goto(`/intentions/${id}`);
  await expect(page.getByTestId("intention-status")).toHaveAttribute("data-state", state);
  await expect(page.getByTestId("journey-note")).toHaveAttribute("data-state", state);
  await page.goto("/intentions");
  const row = page.locator('[data-testid="intention-row"]').filter({
    has: page.locator(`a[href="/intentions/${id}"]`),
  });
  await expect(row.getByTestId("intention-status")).toHaveAttribute("data-state", state);
  // The panel beside the list shows the latest: this one, just asked.
  const preview = page.getByTestId("intention-preview");
  if (await preview.isVisible()) {
    await row.getByRole("link").click();
    await expect(preview.getByTestId("intention-status")).toHaveAttribute("data-state", state);
  }
  return state;
}

test.describe("An intention's journey", () => {
  test("the same intention, the same state, on every screen — as the API says", async ({
    page,
  }) => {
    await signIn(page);
    const id = await ask(page, `Qui est responsable d'auth-service ? (${Date.now()})`);
    // Queued, no worker here: ready, LEKA on it — not « analysing ».
    expect(await everywhere(page, id)).toBe("ready");

    analyse(id);
    expect(await everywhere(page, id)).toBe("result_available");
    await page.goto(`/intentions/${id}/results`);
    await expect(page.getByTestId("analysis-summary")).toBeVisible();
    await page.goto(`/intentions/${id}/history`);
    await expect(page.getByTestId("intention-event").last()).toBeVisible();
    await expect(page.getByTestId("intention-status")).toHaveAttribute(
      "data-state",
      "result_available",
    );
  });

  test("changed after its analysis: version 2, the earlier result never shown as its result", async ({
    page,
  }) => {
    await signIn(page);
    const id = await ask(page, `Qui est responsable d'auth-service ? (${Date.now()})`);
    analyse(id);
    await page.goto(`/intentions/${id}/results`);
    await expect(page.getByTestId("intention-results")).toBeVisible();

    const changed = await page.request.post(`${API}/${id}/ask`, {
      data: { text: `Qui maintient auth-service ? (${Date.now()})` },
      headers: { "X-CSRF-Token": await csrf(page) },
    });
    expect(changed.ok()).toBe(true);
    expect(await everywhere(page, id)).toBe("ready");

    // Its results: none of version 1's, as its own.
    await page.goto(`/intentions/${id}/results`);
    await expect(page.getByTestId("intention-version")).toHaveText("Version 2");
    await expect(page.getByTestId("analysis-answer")).toHaveCount(0);
    await expect(page.getByTestId("analysis-summary")).toHaveCount(0);
    // Its history: its versions apart.
    await page.goto(`/intentions/${id}/history`);
    await expect(page.getByTestId("timeline-version")).toHaveText([
      "Version 1 · remplacée par une version plus récente",
      "Version 2 · en cours",
    ]);

    analyse(id);
    expect(await everywhere(page, id)).toBe("result_available");
    await page.goto(`/intentions/${id}/results`);
    await expect(page.getByTestId("analysis-not-current")).toHaveCount(0);
  });

  test("stopped while analysed: kept, ready, resumed", async ({ page }) => {
    await signIn(page);
    const id = await ask(page, `Qui est responsable d'auth-service ? (${Date.now()})`);
    await page.goto(`/intentions/${id}`);
    await page.getByTestId("intention-stop").click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("Les résultats partiels seront conservés");
    await dialog.getByRole("button", { name: "Arrêter" }).click();

    await expect(page.getByTestId("journey-note")).toHaveAttribute("data-reason", "stopped");
    expect(await said(page, id)).toMatchObject({ state: "ready", reason: "stopped" });
    expect(await everywhere(page, id)).toBe("ready");
    await page.goto(`/intentions/${id}/history`);
    await expect(page.getByTestId("intention-event").last()).toContainText("Analyse arrêtée");

    await page.goto(`/intentions/${id}`);
    await page.getByTestId("journey-resume").click();
    await expect(page.getByTestId("journey-note")).toHaveAttribute("data-reason", "queued");
    analyse(id);
    expect(await everywhere(page, id)).toBe("result_available");
  });

  test("read again while its actions run: still running, never done", async ({ page }) => {
    await signIn(page);
    const id = await approved(page);
    await page.getByTestId("tab-actions").click();
    await page.getByTestId("plan-prepare-button").click();
    await page.getByTestId("plan-start").click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Lancer maintenant" }).click();
    await expect(page.getByTestId("plan-status")).toHaveText("En cours");

    // Refreshed, then come back to from the list: the same, as the API says.
    for (const visit of ["reload", "list"] as const) {
      if (visit === "reload") await page.reload();
      else {
        await page.goto("/intentions");
        await page.goto(`/intentions/${id}/actions`);
      }
      await expect(page.getByTestId("plan-status")).toHaveText("En cours");
      await expect(page.getByTestId("plan-step").getByTestId("step-status")).toHaveText(
        "À confirmer",
      );
      await expect(page.getByTestId("intention-status")).toHaveText(/Action en cours/);
    }
    expect(await everywhere(page, id)).toBe("action_running");
  });
});
