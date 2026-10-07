import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { pythonExecutable, repositoryRoot } from "./python";
import { signIn } from "./sign-in";

/**
 * Intentions analysed, in a real browser (LEKA-388).
 *
 * What a unit test cannot answer: that an intention asked from the
 * composer is analysed from the context assembled for it — by LEKA's own
 * capabilities, on the demo's company — that its page follows the analysis
 * while it runs and shows how it went and what it found, worded, with the
 * evidence and where it came from; that a question answered completes the
 * intention, and an action asked waits for a person.
 *
 * There is no worker here: the analysis the API queues is run as the job
 * runner would, for this intention only.
 */

/** Its analysis, run now — the job the API queued. */
function analyse(intentionId: string): void {
  execFileSync(
    pythonExecutable(),
    [
      "-c",
      [
        "import asyncio, sys, uuid",
        "from sqlalchemy import select",
        "from leka.db import session_factory, system_scope",
        "from leka.intentions import Intention",
        "from leka.intentions.processing import analyse_intention",
        "async def main(intention_id):",
        "    with system_scope():",
        "        async with session_factory() as session:",
        "            workspace = await session.scalar(",
        "                select(Intention.workspace_id).where(Intention.id == intention_id))",
        "    print(await analyse_intention(workspace, intention_id, trigger='created'))",
        "asyncio.run(main(uuid.UUID(sys.argv[1])))",
      ].join("\n"),
      intentionId,
    ],
    { cwd: path.join(repositoryRoot(), "api"), stdio: "inherit" },
  );
}

/** Asked from the composer, followed to its page: its id. */
async function ask(page: Page, words: string): Promise<string> {
  await page.goto("/intentions/new");
  await expect(page.getByRole("checkbox", { name: "acme/backend" })).toBeChecked();
  await page.getByTestId("intention-input").fill(words);
  await page.getByTestId("intention-submit").click();
  await expect(page.getByTestId("intention-step-2")).toBeVisible();
  await page.getByTestId("intention-follow").click();
  await expect(page).toHaveURL(/\/intentions\/[0-9a-f-]{36}$/);
  return page.url().split("/").pop() ?? "";
}

test.describe("Intention analysis", () => {
  test("asked, analysed, how it went and what it found, its evidence", async ({ page }) => {
    await signIn(page);
    const id = await ask(page, `Qui est responsable de auth-service ? (${Date.now()})`);

    // Not analysed yet: on its way, said so.
    await page.getByTestId("tab-analysis").click();
    await expect(page).toHaveURL(/\/analysis$/);
    const head = page.getByTestId("analysis-head");
    await expect(head).toHaveAttribute("data-live", "true");
    await expect(head).toContainText("Analyse en attente");

    analyse(id);

    // Read again while on its way: done, how it went.
    await expect(head).toHaveAttribute("data-live", "false", { timeout: 15_000 });
    await expect(head.getByTestId("analysis-status")).toHaveText("Complète");
    await expect(head.getByTestId("analysis-meta")).toContainText(
      "Analyse n° 1 · à la création",
    );
    const steps = page.getByTestId("analysis-step");
    await expect(steps).toHaveCount(2);
    await expect(steps.nth(0)).toHaveAttribute("data-name", "standing");
    await expect(steps.nth(1)).toHaveAttribute("data-name", "ownership");
    await expect(steps.nth(1)).toHaveAttribute("data-status", "succeeded");
    await expect(steps.nth(1)).toContainText("Responsabilités · pour son objectif");
    // What it found, worded — no proposal.
    await expect(page.getByTestId("analysis-summary")).toContainText(
      "auth-service appartient à Thomas Berger.",
    );
    await expect(page.getByText("Recommandations de LEKA")).toHaveCount(0);
    // Answered: completed, by LEKA.
    await expect(page.getByTestId("intention-status")).toContainText("Terminée");

    // Its evidence: the record that says who owns it, and where from.
    await page.getByTestId("tab-evidence").click();
    const evidence = page.getByTestId("intention-evidence");
    const owner = evidence
      .getByRole("listitem")
      .filter({ hasText: "Thomas Berger possède auth-service" });
    await expect(owner).toBeVisible();
    await expect(owner).toContainText("acme/backend");

    // Its overview and history say it too.
    await page.getByTestId("tab-overview").click();
    await expect(page.getByTestId("intention-summary")).toHaveText(
      "auth-service appartient à Thomas Berger.",
    );
    await page.getByTestId("tab-history").click();
    await expect(page.getByTestId("intention-event").last()).toContainText("LEKA a répondu");
  });

  test("an action asked waits for a person, what it reaches said", async ({ page }) => {
    await signIn(page);
    const id = await ask(page, `Redémarre auth-service en production (${Date.now()})`);
    analyse(id);

    await page.goto(`/intentions/${id}/analysis`);
    await expect(page.getByTestId("analysis-head")).toHaveAttribute("data-live", "false");
    const action = page.getByTestId("analysis-step").filter({ hasText: "Action demandée" });
    await expect(action).toHaveAttribute("data-status", "succeeded");
    await expect(page.getByTestId("analysis")).toContainText(
      "Demandé : Redémarrer auth-service. Une personne doit l'approuver avant toute exécution.",
    );
    await expect(page.getByTestId("analysis")).toContainText("payment-api");
    // Never LEKA's to decide.
    await expect(page.getByTestId("intention-status")).toContainText("À décider");
  });
});
