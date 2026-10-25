import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { MODEL_ENV } from "./model-env";
import { pythonExecutable, repositoryRoot } from "./python";
import { expectShellReady, expectSignedIn, LANDING, loginAnswer } from "./sign-in";

/**
 * An Enterprise organisation (2026-10-25), in a real browser — made as LEKA
 * makes one, `python -m leka.ops.enterprise provision`, then its account
 * signed in for the first time.
 *
 * What a unit test cannot answer: that its first sign-in is clean — its
 * badge, its name, nothing connected said in grey, Confluence first, no
 * demonstration —; that nothing commercial is shown anywhere — no price, no
 * bundle, no plan to compare: « Contrat »; that its dedicated agent comes
 * first, « Conçu pour » it; that its logo, given by its admin, is in the
 * header.
 *
 * LEKA_E2E_SCREENS: a folder where each screen is kept, to be looked at.
 * LEKA_E2E_PACKAGE: where the architect's package it downloads is kept, its
 * commands as the dialog shows them beside it (.commands.txt) — to install
 * it by them.
 */

const SCREENS = process.env.LEKA_E2E_SCREENS;
const PACKAGE = process.env.LEKA_E2E_PACKAGE;
// The organisation's own instructions, as LEKA is given them — never a real
// one in the code (2026-10-25).
const OWN = "PROMPT SYSTÈME — AGENT « ARCHITECTE APPLICATIF » — consignes de l'organisation\n□ PPTX + PDF livrés.\n";
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);

function provision(email: string, organisation: string, password: string, instructions?: string): void {
  execFileSync(
    pythonExecutable(),
    [
      "-m",
      "leka.ops.enterprise",
      "provision",
      "--email",
      email,
      "--organisation",
      organisation,
      "--agent",
      "application-architecture",
      "--contact-name",
      "Ada Lovelace",
      "--contact-email",
      "ada@leka.example",
      // Its own instructions through the standard input, as on the box.
      ...(instructions === undefined ? [] : ["--instructions", "-"]),
    ],
    {
      cwd: path.join(repositoryRoot(), "api"),
      // The first password from the environment, never on the command line.
      env: { ...process.env, ...MODEL_ENV, LEKA_ENTERPRISE_PASSWORD: password },
      input: instructions,
      stdio: [instructions === undefined ? "inherit" : "pipe", "inherit", "inherit"],
    },
  );
}

/** A file of a zip, read by Python's own zipfile. */
function unzipped(zip: string, name: string): string {
  return execFileSync(pythonExecutable(), [
    "-c",
    "import sys, zipfile; sys.stdout.write(zipfile.ZipFile(sys.argv[1]).read(sys.argv[2]).decode())",
    zip,
    name,
  ]).toString("utf8");
}

async function signInAs(page: Page, email: string, password: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Adresse e-mail", { exact: true }).fill(email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(password);
  const answered = loginAnswer(page);
  await page.getByRole("button", { name: "Se connecter" }).click();
  expectSignedIn(await answered);
  await expect(page).toHaveURL(LANDING);
  await expectShellReady(page);
}

async function kept(page: Page, name: string): Promise<void> {
  if (SCREENS) await page.screenshot({ path: path.join(SCREENS, `${name}.png`), fullPage: true });
}

/** Nothing commercial on the page: no price, no bundle, no plan to compare.
 * `money`: false where a sum is only an example of how numbers are written
 * (Paramètres › Région). */
async function nothingSold(page: Page, { money = true }: { money?: boolean } = {}): Promise<void> {
  const main = page.locator("#main-content");
  if (money) await expect(main).not.toContainText("€");
  await expect(main).not.toContainText("par million de tokens");
  await expect(main).not.toContainText(/bundle/i);
  await expect(main).not.toContainText(/crédits? IA/i);
  await expect(page.getByTestId("plan-badge")).toHaveCount(0);
  await expect(page.getByTestId("agent-buy")).toHaveCount(0);
}

test.describe("An Enterprise organisation", () => {
  test.use({ viewport: { width: 1536, height: 1024 } });

  test("its first sign-in: its badge, nothing connected, Confluence first, nothing sold, « Contrat »", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    const stamp = Date.now();
    const organisation = `Organisation pilote ${stamp}`;
    const email = `pilote-${stamp}@leka.example`;
    const password = `Pilote-${stamp}-mot-de-passe`;
    provision(email, organisation, password);
    // Run twice: the same organisation, nothing doubled — then its architect
    // given its own instructions.
    provision(email, organisation, password);
    provision(email, organisation, password, OWN);
    await signInAs(page, email, password);

    // The header: « Entreprise » and its name — its contract one click away.
    await expect(page.getByTestId("enterprise-badge")).toHaveText("Entreprise");
    await expect(page.getByTestId("enterprise-badge")).toHaveAttribute("href", "/billing");
    await expect(page.getByTestId("workspace-switcher")).toContainText(organisation);

    // The home: nothing connected — the question locked, Confluence first
    // (2026-10-25: one was asked with nothing connected); no demonstration.
    const lock = page.getByTestId("source-lock");
    await expect(lock).toHaveAttribute("data-what", "ask");
    await expect(lock).toContainText("Connectez une source pour poser vos questions");
    await expect(page.getByTestId("source-lock-connect")).toHaveText("Connecter Confluence");
    await expect(page.getByTestId("intention-input")).toHaveCount(0);
    await expect(page.getByTestId("first-steps")).toHaveCount(0);
    await expect(page.getByTestId("home-health")).toHaveText("Aucune source connectée");
    await expect(page.getByTestId("home-environment")).toHaveAttribute("data-sources", "none");
    await expect(page.getByTestId("explore-demo")).toHaveCount(0);
    // Its dedicated agent first: what it does, « Lancer ».
    const made = page.getByTestId("home-dedicated");
    await expect(made).toContainText(`Conçus pour ${organisation}`);
    await expect(made.getByTestId("home-dedicated-agent")).toContainText(
      "Génère la documentation d'architecture applicative structurée ArchiMate à partir de votre Confluence",
    );
    // « Lancer »: its perimeter chosen first — none yet: Confluence to connect.
    await expect(made.getByTestId("home-dedicated-launch")).toHaveAttribute("href", "/architecte");
    await nothingSold(page);
    await kept(page, "01-accueil");

    // « Installer dans votre environnement »: three ways, its package downloaded.
    await made.getByTestId("install-open").click();
    const install = page.getByTestId("install-dialog");
    await expect(install).toContainText("rien ne passe par LEKA");
    // Its button, clicked: the zip, its organisation's instructions in it.
    await install.getByTestId("install-system-macos").click();
    const downloading = page.waitForEvent("download");
    await install.getByTestId("install-download").first().click();
    const download = await downloading;
    expect(download.suggestedFilename()).toMatch(/^leka-architect-.*\.zip$/);
    const saved = PACKAGE ?? test.info().outputPath("leka-architect.zip");
    await download.saveAs(saved);
    expect(unzipped(saved, "leka-architect/leka_architect/consignes.md")).toBe(OWN);
    expect(unzipped(saved, "leka-architect/copilot/.github/prompts/architecte-applicatif.prompt.md")).toContain(OWN.trim());
    if (PACKAGE) {
      const shown = await install.locator("pre").allTextContents();
      writeFileSync(`${PACKAGE}.commands.txt`, shown.join("\n# ----\n"));
    }
    await page.getByTestId("install-tab-mcp").click();
    await expect(install).toContainText('"args": ["mcp"]');
    await kept(page, "01b-installer");
    const zip = await page.request.get(
      "http://localhost:8000/api/v1/capabilities/application-architecture/package",
    );
    expect(zip.ok()).toBe(true);
    expect(zip.headers()["content-type"]).toBe("application/zip");
    await page.keyboard.press("Escape");
    await expect(install).toBeHidden();
    await made.getByTestId("home-dedicated-launch").click();
    await expect(page.getByTestId("architect-no-source")).toContainText("Aucun Confluence n'est connecté");
    await page.goto("/overview");

    // « Mon environnement » locked too, the way to a source said.
    await page.goto("/environment");
    await expect(page.getByTestId("source-lock")).toHaveAttribute("data-what", "environment");
    // Asked all the same, the server refuses it.
    const csrf = (await page.context().cookies()).find((c) => c.name === "leka_csrf")?.value ?? "";
    const refused = await page.request.post("http://localhost:8000/api/v1/intentions", {
      data: { text: "Pourquoi Billing API est lente ?" },
      headers: { "X-CSRF-Token": csrf },
    });
    expect(refused.status()).toBe(409);
    await page.goto("/overview");

    // Confluence's connection, opened at once.
    await page.getByTestId("source-lock-connect").click();
    await expect(page).toHaveURL(/\/sources$/);
    // On its connection, not the list of every tool.
    await expect(page.getByRole("dialog")).toContainText("Confluence");
    await expect(page.getByRole("dialog")).not.toContainText("Asana");
    await kept(page, "02-connecter-confluence");
    await page.keyboard.press("Escape");

    // The agents: its dedicated one first, then every standard one, by domain.
    await page.goto("/capabilities");
    const dedicated = page.getByTestId("catalogue-dedicated");
    await expect(dedicated).toContainText("Agents dédiés");
    await expect(dedicated).toContainText(`Conçus pour ${organisation}`);
    await expect(dedicated.locator('[data-key="application-architecture"]')).toContainText("Architecte applicatif");
    await expect(page.getByTestId("catalogue-all-agents")).toContainText("Agents disponibles");
    await expect(page.getByTestId("bundles")).toHaveCount(0);
    await expect(page.getByTestId("catalogue-figures")).toHaveCount(0);
    await expect(page.getByTestId("agent-state").first()).toBeVisible();
    await nothingSold(page);
    await kept(page, "03-agents");

    await page.goto("/capabilities/application-architecture");
    await expect(page.getByTestId("agent-dedicated")).toHaveText(`Conçu pour ${organisation}`);
    await expect(page.getByTestId("agent-contract")).toContainText("il n'est pas vendu");
    await nothingSold(page);
    await kept(page, "04-architecte");

    // « Contrat », never a bill — the plans' page too.
    await page.goto("/billing");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Contrat");
    await expect(page.getByTestId("contract-type")).toContainText("Entreprise");
    await expect(page.getByTestId("contract-organisation")).toContainText(organisation);
    await expect(page.getByTestId("contract-members")).toContainText("1");
    await expect(page.getByTestId("contract-contact")).toContainText("Ada Lovelace");
    await expect(page.getByTestId("contract-includes")).toContainText("Vos agents dédiés : Architecte applicatif");
    await nothingSold(page);
    await kept(page, "05-contrat");
    await page.goto("/billing/plans");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Contrat");
    await page.getByTestId("user-menu").click();
    await expect(page.getByTestId("menu-billing")).toHaveText("Contrat");
    await page.keyboard.press("Escape");

    // Its logo, given by its admin: in the header.
    await page.goto("/billing");
    await page.getByTestId("contract-logo-input").setInputFiles({ name: "logo.png", mimeType: "image/png", buffer: PNG });
    await expect(page.getByTestId("contract-logo-image")).toBeVisible();
    await expect(page.getByTestId("header-logo")).toBeVisible();
    await kept(page, "06-logo");

    // Its owner reads the audit trail: who ran which agent, on what.
    await page.goto("/governance?tab=agents");
    await expect(page.getByRole("tab", { name: "Journal", exact: true })).toBeVisible();
    await expect(page.getByTestId("agent-usage-tab")).toBeVisible();

    // Every screen of running it answers.
    for (const [address, name] of [
      ["/team", "07-equipe"],
      ["/governance?tab=security", "08-securite"],
      ["/governance?tab=agents", "09-usage-agents"],
      ["/governance?tab=journal", "10-journal"],
      ["/environment", "11-environnement"],
      ["/intentions", "12-historique"],
      ["/settings", "13-configuration"],
    ] as const) {
      await page.goto(address);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await page.waitForLoadState("networkidle");
      await expect(page.getByRole("alert").filter({ hasText: /erreur|error/i })).toHaveCount(0);
      await nothingSold(page, { money: address !== "/settings" });
      await kept(page, name);
    }
  });
});
