import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { clearRateLimits } from "./global-setup";
import { analyse } from "./intention-helpers";
import { linkFromEmail } from "./outbox";
import { pythonExecutable, repositoryRoot } from "./python";
import { expectSignedIn, loginAnswer } from "./sign-in";

/**
 * Activation (LEKA-445): from a new account to a first analysis, without
 * help — registered, the address confirmed, the workspace created, the
 * tools left for later; the overview then says what LEKA does, that
 * nothing is connected yet, and offers questions said to be examples. One
 * asked with nothing to read says why it cannot start. GitHub connected and
 * read, the overview says it is ready; a question of the person's own is
 * asked from it, analysed as the job runner would, and answered from the
 * records — and the first steps, done, are gone.
 */

const PASSWORD = "a long enough passphrase";

test("a new account goes from its workspace to a first analysis", async ({
  page,
}) => {
  const email = `e2e-activation-${Date.now()}@leka.example`;
  // One registration more than the hour allows from one address, with
  // emails.spec's three: forgotten before it and after, whichever runs first.
  clearRateLimits();
  await page.goto("/register");
  await page.getByLabel("Prénom", { exact: true }).fill("Nora");
  await page.getByLabel("Nom", { exact: true }).fill("Diallo");
  await page.getByLabel("Entreprise", { exact: true }).fill("Globex");
  await page.getByLabel("E-mail professionnel", { exact: true }).fill(email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Créer le compte" }).click();
  await expect(
    page.getByText("Consultez votre boîte de réception"),
  ).toBeVisible();
  clearRateLimits();
  await page.goto(
    (await linkFromEmail(email, "Confirmez votre adresse e-mail LEKA")).href,
  );
  await expect(page.getByText("Adresse confirmée")).toBeVisible();

  await page.goto("/login");
  await page.getByLabel("Adresse e-mail", { exact: true }).fill(email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  const answered = loginAnswer(page);
  await page.getByRole("button", { name: "Se connecter" }).click();
  expectSignedIn(await answered);
  await page.getByRole("button", { name: "Créer l'espace" }).click();
  await expect(page).toHaveURL(/\/welcome$/);

  // Someone who knows what to do is not held: later, straight to the overview.
  await page.getByRole("link", { name: "Plus tard" }).click();
  await expect(page).toHaveURL(/\/overview$/);
  const steps = page.getByTestId("first-steps");
  await expect(steps).toHaveAttribute("data-stage", "empty");
  await expect(steps).toContainText("LEKA lit vos outils");
  await expect(page.getByTestId("first-steps-stage")).toContainText(
    "Aucune source n'est connectée",
  );
  await expect(page.getByTestId("first-steps-action")).toHaveAttribute(
    "href",
    "/welcome",
  );
  // Nothing read: said that LEKA cannot answer yet — no example (LEKA-470).
  await expect(page.getByTestId("first-steps-ask")).toContainText(
    "LEKA pourra y répondre une fois une source lue",
  );

  // One asked all the same, carried from the home's bar to the full step by
  // the paperclip: with nothing to read, why nothing starts is said.
  await page
    .getByTestId("intention-input")
    .fill("Qu'est-ce qui a changé dans le code cette semaine ?");
  await page
    .getByRole("button", { name: "Joindre un fichier (à l'étape suivante)" })
    .click();
  await expect(page).toHaveURL(/\/intentions\/new\?q=/);
  await expect(page.getByTestId("intention-input")).toHaveValue(
    "Qu'est-ce qui a changé dans le code cette semaine ?",
  );
  await page.getByTestId("intention-submit").click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Aucune source connectée" }),
  ).toBeVisible();

  // GitHub connected and read (the stand-in: there is no GitHub here).
  connectGitHub(email);
  await page.goto("/overview");
  await expect(steps).toHaveAttribute("data-stage", "ready");
  await expect(page.getByTestId("first-steps-stage")).toContainText(
    "Prêt : LEKA lit développement.",
  );
  await expect(page.getByTestId("first-steps-ask")).toContainText(
    "Écrivez-la dans la barre ci-dessous",
  );

  // A question of its own, from the overview's box, at any moment.
  await page
    .getByTestId("intention-input")
    .fill("Qui maintient globex/billing ?");
  await page.getByTestId("intention-submit").click();
  // Asked from the box itself (2026-10-14): its page opens on it.
  await expect(page).toHaveURL(/\/intentions\/[0-9a-f-]{36}$/);
  const id = page.url().split("/").pop() ?? "";

  analyse(id);

  // A first analysis worth reading: who, from the records that say so.
  await page.goto(`/intentions/${id}/results`);
  await expect(
    page.getByText("globex/billing est maintenu par Sara K.").first(),
  ).toBeVisible();

  // Read and asked: the first steps are done, and gone.
  await page.goto("/overview");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(steps).toHaveCount(0);
});

/** GitHub, connected and read in the account's workspace: e2e/connect_github.py. */
function connectGitHub(email: string): void {
  execFileSync(
    pythonExecutable(),
    [path.join(__dirname, "connect_github.py"), email],
    {
      cwd: path.join(repositoryRoot(), "api"),
      stdio: "inherit",
    },
  );
}
