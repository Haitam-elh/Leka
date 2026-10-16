import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { analyse, ask } from "./intention-helpers";
import { MODEL_ENV } from "./model-env";
import { pythonExecutable, repositoryRoot } from "./python";
import { signIn } from "./sign-in";

/**
 * An intention's page (LEKA-458), in a real browser, on the demo.
 *
 * The stand-in model proposes no agent, so what a real model proposes for a
 * React migration — four agents of the registry and the plan — is written
 * into the analysis, as the analysis keeps it; the demo workspace is put on
 * Free, LEKA's grant taken back, for the test only. What a unit test cannot
 * answer: that the server's offer reaches the page — the agents as the plan
 * to take runs them (Starter includes code review and test analysis, Karim's
 * matrix), the plan that costs least, the launch offer and the price after
 * it, the total — and that nothing is bought without a confirmation saying
 * it all.
 */

// As the registry names them: what a real analysis proposes.
const AGENTS: Record<string, [string, string]> = {
  "code-review": ["Revue de code", "development"],
  "application-architecture": ["Architecte applicatif", "architecture"],
  "test-analysis": ["Analyse des tests", "development"],
  "release-analysis": ["Analyse de release", "development"],
};

function run(lines: string[], ...args: string[]): void {
  execFileSync(pythonExecutable(), ["-c", lines.join("\n"), ...args], {
    cwd: path.join(repositoryRoot(), "api"),
    stdio: "inherit",
    env: { ...process.env, ...MODEL_ENV },
  });
}

/** Its analysis, proposing what a model would for a migration. */
function propose(intentionId: string): void {
  run(
    [
      "import asyncio, json, sys, uuid",
      "from sqlalchemy import select",
      "from leka.db import session_factory, system_scope",
      "from leka.intentions.models import IntentionAnalysis",
      "AGENTS = json.loads(sys.argv[2])",
      "async def main(intention_id):",
      "    with system_scope():",
      "        async with session_factory() as session:",
      "            row = await session.scalar(select(IntentionAnalysis).where(",
      "                IntentionAnalysis.intention_id == intention_id).order_by(",
      "                IntentionAnalysis.number.desc()).limit(1))",
      "            proposal = dict((row.result or {}).get('proposal') or {})",
      "            proposal['agents'] = [{'key': k, 'title': t, 'summary': '', 'category': c,",
      "                'why': 'Le travail le demande.', 'deliverables': ['report'], 'asked': [], 'inputs': {},",
      "                'missing': [], 'fields': [], 'credits': None, 'available': True, 'reasons': []}",
      "                for k, (t, c) in AGENTS.items()]",
      "            proposal['steps'] = [",
      "                {'title': 'Analyse du code et des dépendances', 'detail': 'Scan du code. Dépendances impactées.', 'agent': 'code-review'},",
      "                {'title': \"Analyse d'architecture\", 'detail': \"Cartographie de l'architecture actuelle.\", 'agent': 'application-architecture'},",
      "                {'title': 'Analyse des tests', 'detail': 'Tests à créer ou à adapter.', 'agent': 'test-analysis'},",
      "                {'title': 'Plan de migration', 'detail': 'Synthèse des résultats. Plan étape par étape.', 'agent': None}]",
      "            proposal['informative'] = False",
      "            row.result = {**row.result, 'proposal': proposal}",
      "            await session.commit()",
      "asyncio.run(main(uuid.UUID(sys.argv[1])))",
    ],
    intentionId,
    JSON.stringify(AGENTS),
  );
}

/** The demo workspace on a plan — LEKA's grant taken back, or given again. */
function onPlan(plan: string, granted: boolean): void {
  run(
    [
      "import asyncio, sys",
      "from sqlalchemy import select",
      "from leka.db import session_factory, system_scope, workspace_scope",
      "from leka.platform import Workspace",
      "from leka.billing import end, grant",
      "from leka.billing.entitlements import EVERY",
      "from leka.governance import set_plan",
      "async def main(plan, granted):",
      "    with system_scope():",
      "        async with session_factory() as session:",
      "            ws = await session.scalar(select(Workspace).where(Workspace.slug == 'acme'))",
      "    with workspace_scope(ws.id):",
      "        async with session_factory() as session:",
      "            await set_plan(session, ws.id, plan, by='e2e', reason='LEKA-458')",
      "            if granted == '1':",
      "                await grant(session, ws.id, by='e2e', reason='LEKA-458')",
      "            else:",
      "                await end(session, ws.id, key=EVERY)",
      "            await session.commit()",
      "asyncio.run(main(sys.argv[1], sys.argv[2]))",
    ],
    plan,
    granted ? "1" : "0",
  );
}

test.describe("An intention's page", () => {
  // The demo as the seed leaves it — on Business, LEKA's grant given —
  // for the specs after this one.
  test.afterEach(() => onPlan("business", true));

  test("on Free: the agents, the least plan, the launch offer and the total — nothing bought unasked", async ({
    page,
  }) => {
    test.setTimeout(120_000);
    await signIn(page);
    const id = await ask(
      page,
      `Analyse les risques de passer notre application front de React 17 à React 18 (${Date.now()})`,
    );
    analyse(id);
    propose(id);
    onPlan("free", false);
    await page.goto(`/intentions/${id}`);

    await expect(page.getByTestId("intention-detail-page")).toBeVisible();
    await expect(page.getByTestId("detail-request")).toContainText("React 17 à React 18");
    // Included with the plan to take, said so; the others, options at the
    // catalogue's price.
    const agents = page.getByTestId("detail-agent");
    await expect(agents).toHaveCount(4);
    await expect(agents.filter({ hasText: "Inclus avec Starter" })).toHaveCount(2);
    await expect(agents.filter({ hasText: "/ mois" })).toHaveCount(2);
    await expect(page.getByTestId("detail-agents")).toContainText(
      "Agents disponibles uniquement via un abonnement",
    );
    // The plan that costs least, its launch offer and the price after.
    const plan = page.getByTestId("detail-plan");
    await expect(plan).toContainText("Starter");
    await expect(plan).toContainText("59 €");
    const total = page.getByTestId("detail-total");
    // 47,20 € (Starter, −20 %) + 25 + 25: the two experts it does not include.
    await expect(total).toContainText("97,20 €");
    // Paid for: the plan and the two it does not include, never the two it does.
    await expect(total).toContainText("Abonnement + 2 agents");
    await expect(page.getByTestId("detail-then")).toContainText("puis 109 €");
    await expect(total).toContainText("renouvelé automatiquement");
    // The plan, step by step, each agent beside its step; LEKA Assistant
    // for what LEKA does itself.
    await expect(page.getByTestId("detail-plan-step")).toHaveCount(4);
    await expect(page.getByTestId("detail-plan-steps")).toContainText("Inclus avec l'abonnement");

    // One fewer: the total follows, from the server.
    await page.getByTestId("detail-agent-choose").nth(3).uncheck();
    await expect(total).toContainText("72,20 €");

    // Nothing bought without a confirmation that says it all.
    await page.getByTestId("detail-activate").click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("Étape 1 : l'abonnement Starter");
    await expect(dialog).toContainText("renouvelé automatiquement");
    await dialog.getByRole("button", { name: "Annuler" }).click();
    await expect(page).toHaveURL(new RegExp(`/intentions/${id}$`));
  });
});
