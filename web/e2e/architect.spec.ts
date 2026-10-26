import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { MODEL_ENV } from "./model-env";
import { pythonExecutable, repositoryRoot } from "./python";
import { signIn } from "./sign-in";

/**
 * The architect on a Confluence space (2026-10-25), in a real browser, on
 * the demo: a Confluence source synced — its space, four pages three deep,
 * written as extraction leaves them —, its « Arborescence », « Documenter
 * cet espace », the perimeter chosen, an intention asked and the architect
 * started; run by the worker's own code; its dossier delivered — PDF, Word,
 * Markdown, JSON —, each section citing its pages, a link to each.
 *
 * The model is the stand-in (e2e/model-stub.mjs): it cites the pages it is
 * shown.
 */

const SITE = "https://acme.atlassian.net/wiki/spaces/ARCHI/pages";

function run(lines: string[], ...args: string[]): string {
  return execFileSync(pythonExecutable(), ["-c", lines.join("\n"), ...args], {
    cwd: path.join(repositoryRoot(), "api"),
    env: { ...process.env, ...MODEL_ENV },
  })
    .toString()
    .trim();
}

/** A Confluence source of the demo's, as a sync and extraction left it. */
function synced(name: string): string {
  return run(
    [
      "import asyncio, hashlib, sys, uuid",
      "from datetime import UTC, datetime",
      "from sqlalchemy import select, text",
      "from leka.connectors import SourceKind, SourceService",
      "from leka.db import session_factory, system_scope, workspace_scope",
      "from leka.ingestion.models import ExtractedRecordRow, ExtractionStatus, SourceRecord",
      "from leka.platform import Workspace",
      "from leka.db import load_schema",
      "load_schema()  # every table, as the API has",
      "NOW = datetime.now(UTC)",
      `SITE = "${SITE}"`,
      "PAGES = [('100', 'Accueil', None, 'Le SI de facturation.'),",
      "         ('101', 'Applications', '100', 'Billing API appelle Ledger.'),",
      "         ('102', 'Billing API', '101', 'Composant applicatif.'),",
      "         ('103', 'Infrastructure', '100', 'Kubernetes.')]",
      "async def main(name):",
      "    with system_scope():",
      "        async with session_factory() as session:",
      "            ws = (await session.scalar(select(Workspace).where(Workspace.slug == 'acme'))).id",
      "    with workspace_scope(ws):",
      "        async with session_factory() as session:",
      "            made = await SourceService(session, ws, actor_user_id=None).create(",
      "                SourceKind.CONFLUENCE, name, {'site': 'acme'},",
      "                {'token': 'e2e-token-0123456789abcdef', 'email': 'e2e@acme.example'})",
      "            await session.execute(text(\"UPDATE sources SET status = 'active' WHERE id = :s\"), {'s': made.id})",
      "            async def keep(kind, external_id, container, result):",
      "                checksum = hashlib.sha256(f'{made.id}{kind}{external_id}'.encode()).hexdigest()",
      "                record = SourceRecord(workspace_id=ws, id=uuid.uuid4(), source_id=made.id, kind=kind,",
      "                    external_id=external_id, container=container, checksum=checksum,",
      "                    first_seen_at=NOW, last_seen_at=NOW)",
      "                session.add(record)",
      "                await session.flush()",
      "                session.add(ExtractedRecordRow(workspace_id=ws, id=uuid.uuid4(), source_id=made.id,",
      "                    source_record_id=record.id, kind=kind, status=ExtractionStatus.EXTRACTED,",
      "                    extractor=f'confluence.{kind}', extractor_version=1, checksum=checksum,",
      "                    result=result, extracted_at=NOW))",
      "            await keep('spaces', 's-ARCHI', 'ARCHI', {'title': 'Architecture', 'metadata': {'key': 'ARCHI'}})",
      "            for pid, title, parent, body in PAGES:",
      "                await keep('pages', pid, 'ARCHI', {'title': title, 'url': f'{SITE}/{pid}',",
      "                    'content': [{'role': 'body', 'format': 'text', 'text': body}],",
      "                    'references': [{'role': 'parent', 'kind': 'document', 'external_id': parent}] if parent else []})",
      "            await session.commit()",
      "            print(made.id)",
      "asyncio.run(main(sys.argv[1]))",
    ],
    name,
  );
}

/** The run, as a worker runs it. */
function worked(runId: string): void {
  run(
    [
      "import asyncio, sys, uuid",
      "from sqlalchemy import select",
      "from leka.capabilities import execute_run",
      "from leka.db import session_factory, system_scope",
      "from leka.platform import Workspace",
      "from leka.db import load_schema",
      "load_schema()",
      "async def main(run_id):",
      "    with system_scope():",
      "        async with session_factory() as session:",
      "            ws = (await session.scalar(select(Workspace).where(Workspace.slug == 'acme'))).id",
      "    print(await execute_run(ws, uuid.UUID(run_id)))",
      "asyncio.run(main(sys.argv[1]))",
    ],
    runId,
  );
}

test.describe("The architect on a Confluence space", () => {
  test.use({ viewport: { width: 1440, height: 1000 } });

  test("its tree, its perimeter chosen, its dossier delivered — each section citing its pages", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const name = `Confluence Archi ${Date.now()}`;
    const source = synced(name);
    await signIn(page);

    // « Arborescence »: four pages, three deep, parent and child.
    await page.goto(`/sources/${source}`);
    const tree = page.getByTestId("source-tree");
    await expect(tree.getByTestId("tree-space-counts")).toHaveText("4 pages · profondeur 3");
    await expect(tree.getByRole("link", { name: "Accueil" })).toHaveAttribute("href", `${SITE}/100`);
    await expect(tree.getByTestId("tree-page")).toHaveCount(4);

    // « Documenter cet espace »: the perimeter chosen, the subject filled.
    await tree.getByTestId("tree-space-document").click();
    await expect(page).toHaveURL(/\/architecte\?source=.*&space=ARCHI$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Architecte applicatif");
    await expect(page.getByRole("radio", { name: /Architecture/ })).toBeChecked();
    await expect(page.getByTestId("architect-subject")).toHaveValue("Architecture");
    await page.getByTestId("architect-subject").fill("Facturation");
    await page.getByTestId("architect-launch-submit").click();
    await expect(page).toHaveURL(/\/intentions\/[0-9a-f-]+\/deliverable\?run=[0-9a-f-]+$/);
    const runId = new URL(page.url()).searchParams.get("run") ?? "";

    worked(runId);
    await page.reload();
    const files = page.getByTestId("agent-run-deliverables");
    await expect(files.getByRole("link")).toHaveText(["Télécharger le PDF", "Word", "Markdown", "JSON"]);
    await expect(files).toContainText("Dossier ArchiMate : chaque section cite ses pages Confluence.");
    // The dossier itself, each section citing its pages by their link.
    const said = page.getByTestId("deliverable");
    await expect(said).toContainText("Couche application");
    await expect(said.getByRole("link", { name: "Billing API" }).first()).toHaveAttribute("href", `${SITE}/102`);
    const pdf = await page.request.get(
      `http://localhost:8000/api/v1/agent-runs/${runId}/deliverables/pdf`,
    );
    expect(pdf.ok()).toBe(true);
    expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");
  });
});
