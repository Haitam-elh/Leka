import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { analyse, ask, openStep } from "./intention-helpers";
import { MODEL_ENV } from "./model-env";
import { pythonExecutable, repositoryRoot } from "./python";
import { signIn } from "./sign-in";

/**
 * The LLM runtime, end to end (LEKA-429): LEKA's default model — Gemini 3.8
 * Flash, at the tests' stand-in (e2e/model-stub.mjs) — doing real work
 * through the real gateway and runtime, in a real browser.
 *
 * An Intention flow: words the rules cannot read — no goal said — read by
 * the model, so the intention is analysed instead of stopped for a
 * question; what it understood said, and by which model.
 *
 * A Capability flow: the synthesis — a capability written by the model
 * LEKA assigned to it (agents/models.yaml, LEKA-530) — answers the analysis
 * in words, each point citing what it rests on; its sheet says it is ready,
 * never which model.
 *
 * Both kept, for the LEKA team only: `python -m leka.metering.cli usage`
 * says each call, its model and the version that answered — Paramètres
 * says nothing of it.
 */

test.describe("LLM runtime", () => {
  test("an intention read and answered by the model, a capability run by it", async ({
    page,
  }) => {
    await signIn(page);
    const id = await ask(page, `auth-service, c'est à qui de voir ça ? (${Date.now()})`);

    // Read by the model: its goal settled, not stopped for a question —
    // what LEKA understood is step 1's.
    await openStep(page, "overview");
    const understood = page.getByTestId("intention-brief");
    await expect(understood.locator('[data-testid="brief-slot"][data-slot="goal"]')).toContainText(
      "Trouver le responsable",
    );
    await expect(understood.getByTestId("brief-restated")).toContainText("Lu par Gemini 3.8 Flash");
    await expect(understood.getByTestId("brief-questions")).toHaveCount(0);

    analyse(id);

    // Answered: the synthesis ran after the rules, its answer leads.
    await page.goto(`/intentions/${id}/analysis`);
    const synthesis = page.locator('[data-testid="analysis-step"][data-name="synthesis"]');
    await expect(synthesis).toHaveAttribute("data-status", "succeeded");
    await page.goto(`/intentions/${id}/results`);
    const answer = page.getByTestId("analysis-answer");
    await expect(answer).toContainText("D'après l'analyse");
    await expect(answer.getByTestId("answer-point").first()).toContainText(/éléments? cités?/);
    await expect(answer).toContainText("Rédigée par Gemini 3.8 Flash");

    // The capability: ready, on the model LEKA chose — never which one.
    await page.goto("/capabilities/synthesis");
    await expect(page.getByTestId("capability-availability")).toContainText("Disponible");
    await expect(page.getByTestId("capability-model")).toContainText("prêt : le modèle choisi par LEKA");

    // Kept, for the LEKA team: each call, its model, the version that
    // answered — read by its own command, never shown in Paramètres.
    const calls = JSON.parse(
      execFileSync(
        pythonExecutable(),
        ["-m", "leka.metering.cli", "usage", "--operation", "intention.understanding", "--format", "json"],
        { cwd: path.join(repositoryRoot(), "api"), encoding: "utf8", env: { ...process.env, ...MODEL_ENV } },
      ),
    ) as { version: string | null; provider: string; currency: string }[];
    expect(calls.some((call) => call.version === "gemini-3.8-flash-e2e")).toBe(true);
    expect(calls[0]?.currency).toBe("USD");
    await page.goto("/settings");
    await expect(page.locator("#main-content")).not.toContainText("gemini-3.8-flash-e2e");
  });
});
