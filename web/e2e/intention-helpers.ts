import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, type Page } from "@playwright/test";

import { pythonExecutable, repositoryRoot } from "./python";

/**
 * Asking an intention, and analysing it as the job runner would — for the
 * specs of its analysis (LEKA-388) and its decision (LEKA-390). There is no
 * worker in these tests: the analysis the API queues is run here, for one
 * intention only.
 */

/** Its analysis, run now — the job the API queued. */
export function analyse(intentionId: string): void {
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
export async function ask(page: Page, words: string): Promise<string> {
  await page.goto("/intentions/new");
  await expect(page.getByRole("checkbox", { name: "acme/backend" })).toBeChecked();
  await page.getByTestId("intention-input").fill(words);
  await page.getByTestId("intention-submit").click();
  await expect(page.getByTestId("intention-step-2")).toBeVisible();
  await page.getByTestId("intention-follow").click();
  await expect(page).toHaveURL(/\/intentions\/[0-9a-f-]{36}$/);
  return page.url().split("/").pop() ?? "";
}
