import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { MODEL_ENV } from "./model-env";
import { pythonExecutable, repositoryRoot } from "./python";
import { signIn } from "./sign-in";

/**
 * « Régler maintenant » on every agent's deliverable, in a real browser
 * (Haitam, 2026-10-24: « vérifie que pour tous les agents, à la fin du
 * livrable, quand je clique sur le bouton, ça fait bien les actions »).
 *
 * Each agent on sale is given a finished deliverable of its own — its
 * summary, its plan — on one intention; then, on its page:
 * - its PDF downloads;
 * - its own action comes first, and every action it offers acts: the fix
 *   or the tests start the agent that writes them, on its repository, its
 *   deliverable opened; the tickets and the pages open their form; the code
 *   change's own change is written again when there is none.
 *
 * No worker here: a run asked is queued, which is what a click must do.
 */

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const REPORT = [
  "## Résumé",
  "",
  "Verdict : **À reprendre** — deux constats à corriger.",
  "",
  "## Constats",
  "",
  "| Où | Constat |",
  "|---|---|",
  "| `api/app/main.py` | Un délai manque |",
  "",
  "## Plan d'action",
  "",
  "1. Ajouter un délai à l'appel sortant.",
  "2. Écrire le test qui le prouve.",
].join("\n");

/** An intention, and a finished deliverable for every agent on sale on it:
 * its id, and each agent's key → its run's id. */
function delivered(): { intention: string; runs: Record<string, string> } {
  const out = execFileSync(
    pythonExecutable(),
    [
      "-c",
      [
        "import asyncio, json, sys, uuid",
        "from datetime import UTC, datetime",
        "from sqlalchemy import select",
        "import leka.schema",
        "from leka.billing import catalogue as commercial",
        "from leka.capabilities.models import AgentRun",
        "from leka.capabilities.registry import catalogue as definitions",
        "from leka.db import session_factory, system_scope, workspace_scope",
        "from leka.identity import User",
        "from leka.intentions import Intention",
        "from leka.platform import Workspace",
        "async def main(report):",
        "    sold = set(commercial().add_ons.agents)",
        "    found = {d.key: d for d in definitions() if d.key in sold}",
        "    with system_scope():",
        "        async with session_factory() as session:",
        "            ws = await session.scalar(select(Workspace).where(Workspace.slug == 'acme'))",
        "            nora = await session.scalar(select(User).where(User.email == 'nora@acme.example'))",
        "    now = datetime.now(UTC)",
        "    made = {}",
        "    intention = uuid.uuid4()",
        "    with workspace_scope(ws.id):",
        "        async with session_factory() as session:",
        "            session.add(Intention(workspace_id=ws.id, id=intention,",
        "                text='Fais la revue de la PR #12 de acme/backend', title='Revue de la PR #12',",
        "                scope={}, answers=[], status='submitted', status_changed_at=now,",
        "                created_by=nora.id, events_count=0, version=1))",
        "            await session.flush()",
        "            for key, d in sorted(found.items()):",
        "                run = AgentRun(workspace_id=ws.id, key=key, version=d.version, status='succeeded',",
        "                    inputs={'depot': 'acme/backend'}, requested_by=nora.id,",
        "                    intention_id=intention, format='markdown', output=report,",
        "                    detail={}, queued_at=now, started_at=now, finished_at=now)",
        "                session.add(run)",
        "                await session.flush()",
        "                made[key] = str(run.id)",
        "            await session.commit()",
        "    print(json.dumps({'intention': str(intention), 'runs': made}))",
        "asyncio.run(main(sys.argv[1]))",
      ].join("\n"),
      REPORT,
    ],
    { cwd: path.join(repositoryRoot(), "api"), env: { ...process.env, ...MODEL_ENV } },
  ).toString();
  const lines = out.trim().split("\n");
  return JSON.parse(lines[lines.length - 1]) as { intention: string; runs: Record<string, string> };
}

/** The agent a run is of, as the API says it. */
async function keyOf(page: Page, runId: string): Promise<string> {
  const answer = await page.request.get(`${API}/api/v1/agent-runs/${runId}`);
  expect(answer.ok(), runId).toBe(true);
  return ((await answer.json()) as { key: string }).key;
}

test.describe("Régler maintenant", () => {
  test("every agent's deliverable ends on actions that act", async ({ page }) => {
    test.setTimeout(900_000);
    // A dozen API calls a page, against the API's backstop of 300 a minute
    // per session: when little is left, the walk waits for the window.
    let left = Number.POSITIVE_INFINITY;
    let reset = 0;
    page.on("response", (response) => {
      const said = response.headers()["ratelimit-remaining"];
      if (said === undefined) return;
      left = Number(said);
      reset = Number(response.headers()["ratelimit-reset"] ?? "0");
    });
    const breathe = async () => {
      if (left < 60) {
        await page.waitForTimeout((reset + 1) * 1000);
        left = Number.POSITIVE_INFINITY;
      }
    };

    await signIn(page);
    const { intention, runs } = delivered();
    expect(Object.keys(runs).length).toBeGreaterThan(25);
    const at = (runId: string) => `/intentions/${intention}/deliverable?run=${runId}`;

    for (const [key, runId] of Object.entries(runs)) {
      await breathe();
      await page.goto(at(runId));
      const steps = page.getByTestId("next-steps");
      await expect(steps, key).toHaveAttribute("data-agent", key);
      await expect(page.getByTestId("deliverable-report"), key).toContainText("Résumé");
      // Its PDF, from the top of the deliverable.
      const pdf = await page.request.get(`${API}/api/v1/agent-runs/${runId}/report.pdf`);
      expect(pdf.headers()["content-type"], key).toBe("application/pdf");
      // Reached from the top too.
      await expect(page.getByTestId("deliverable-settle"), key).toHaveAttribute("href", "#next-steps");

      const kinds = await steps
        .getByTestId("next-step")
        .evaluateAll((found) => found.map((each) => (each as HTMLElement).dataset.kind ?? ""));
      expect(kinds.length, key).toBeGreaterThan(0);

      for (const kind of kinds) {
        await breathe();
        if (page.url().indexOf(runId) === -1) await page.goto(at(runId));
        const button = page.getByTestId(`next-step-${kind}`).first();
        if (kind === "issues" || kind === "pages") {
          await button.click();
          // The form opens just below — or says which source to connect.
          await expect(page.getByTestId(`publication-ask-${kind}`), `${key} ${kind}`).toHaveAttribute(
            "aria-expanded",
            "true",
          );
          await expect(
            page.getByTestId("publication-form").or(page.getByTestId("publication-no-source")),
            `${key} ${kind}`,
          ).toBeVisible();
        } else if (kind === "change") {
          // No change kept for this deliverable: written again, never a
          // button that does nothing.
          await expect(button, key).toHaveText("Réécrire la modification");
          const asked = page.waitForResponse(
            (r) => r.url().includes(`/agent-runs/${runId}/change`) && r.request().method() === "POST",
          );
          await button.click();
          expect((await asked).status(), key).toBe(202);
        } else {
          await button.click();
          const form = page.getByTestId("next-step-form");
          await expect(form, `${key} ${kind}`).toBeVisible();
          const writer = await form.getAttribute("data-writer");
          expect(writer, `${key} ${kind}`).toBe(kind === "fix" ? "code-change" : "test-generation");
          await expect(form.getByRole("textbox").first(), `${key} ${kind}`).not.toHaveValue("");
          await form.getByTestId("next-step-start").click();
          // The run asked, its deliverable opened.
          await expect(page, `${key} ${kind}`).not.toHaveURL(new RegExp(`run=${runId}`));
          await expect(page, `${key} ${kind}`).toHaveURL(/run=[0-9a-f-]{36}/);
          const started = new URL(page.url()).searchParams.get("run") ?? "";
          expect(await keyOf(page, started), `${key} ${kind}`).toBe(writer);
        }
      }
    }
  });
});
