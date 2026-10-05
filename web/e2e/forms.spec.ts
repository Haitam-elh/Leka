import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * The four journeys LEKA-342 exists for, clicked through.
 *
 * What a unit test cannot answer here: that the composer's shortcut
 * survives a real browser's key handling, that a confirmation really traps
 * focus and gives it back, and that leaving a dirty form is intercepted.
 * The automated accessibility review of these pages, and of every other
 * core screen, is in accessibility.spec.ts.
 */

/** ⌘ on a Mac, Ctrl everywhere else — the same binding either way. */
const SEND = process.platform === "darwin" ? "Meta+Enter" : "Control+Enter";

test.describe("the intention journey", () => {
  test("carries a question from the overview into step 1 and launches it", async ({ page }) => {
    await signIn(page);

    const question = "Pourquoi l'API de paiement est-elle plus lente depuis hier ?";
    await page.getByTestId("intention-input").fill(question);
    await page.keyboard.press(SEND);

    // The compact box does not analyse anything: it hands the sentence to
    // the screen that does, through the same ?q= the palette uses.
    await expect(page).toHaveURL(/\/intentions\/new\?q=/);
    await expect(page.getByTestId("intention-input")).toHaveValue(question);
    // The workspace's own sources, ticked once they arrive (scripts/seed.py).
    await expect(page.getByRole("checkbox", { name: "acme/backend" })).toBeChecked();

    await page.getByTestId("intention-submit").click();

    // Step 2: the context it asks for, as LEKA read it (LEKA-373).
    await expect(page.getByTestId("intention-step-2")).toBeVisible();
    const scope = page.getByTestId("intent-scope");
    await expect(scope).toContainText("Diagnostic");
    await expect(scope).toContainText("payment-api« payment api »");
    await expect(scope).toContainText("lue dans la demande : « hier »");
    await expect(page.getByTestId("intent-gathered")).toContainText("Service");
    await expect(page.getByTestId("intent-sources")).toBeVisible();

    // Edited, the same context is asked again: version 2 says what LEKA
    // reads differently (LEKA-374).
    await page.getByRole("button", { name: "Modifier" }).click();
    await page.getByTestId("intention-input").fill("Qui est responsable de payment-api ?");
    await page.getByTestId("intention-submit").click();
    const again = page.getByTestId("intent-asked-again");
    await expect(again).toContainText("Version 2 de ce contexte");
    await expect(again).toContainText("nature : Diagnostic → Responsabilité");
    await expect(page.getByTestId("intent-scope")).toContainText("Responsabilité");
  });

  test("refuses to launch a question too short to analyse", async ({ page }) => {
    await signIn(page);
    await page.goto("/intentions/new");

    await page.getByTestId("intention-input").fill("lent ?");

    await expect(page.getByTestId("intention-submit")).toBeDisabled();
  });
});

test.describe("the decision step", () => {
  test("asks before touching anything, and takes no for an answer", async ({ page }) => {
    await signIn(page);
    await page.goto("/intentions/new?step=decision");

    const bar = page.getByRole("region", { name: "Actions sur la sélection" });
    await expect(bar).toBeHidden();

    await page.getByRole("checkbox").first().check();
    await expect(bar).toBeVisible();

    await page.getByRole("button", { name: "Valider et passer à l'action" }).click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toBeVisible();
    // It says what it will affect before it is allowed to affect it.
    await expect(dialog).toContainText("3 services concernés");

    // Backing out leaves the selection exactly as it was.
    await dialog.getByRole("button", { name: "Annuler" }).click();
    await expect(dialog).toBeHidden();
    await expect(bar).toBeVisible();

    await page.getByRole("button", { name: "Valider et passer à l'action" }).click();
    await page
      .getByRole("alertdialog")
      .getByRole("button", { name: "Valider et passer à l'action" })
      .click();

    await expect(page.getByTestId("decision-settled")).toBeVisible();
  });
});

test.describe("the settings form", () => {
  test("refuses an empty name, focuses it, and saves once corrected", async ({ page }) => {
    await signIn(page);
    await page.goto("/settings");

    const name = page.getByLabel("Nom du workspace");
    await name.fill("");
    await page.getByTestId("settings-save").click();

    // The correction starts where the problem is, not with a hunt.
    await expect(name).toBeFocused();
    await expect(page.getByText("Au moins 2 caractères.")).toBeVisible();

    await name.fill("Acme Corporation");
    await page.getByTestId("settings-save").click();

    await expect(page.getByText("Modifications enregistrées")).toBeVisible();
  });

  test("reports what the server refused on the field that caused it", async ({ page }) => {
    await signIn(page);
    await page.goto("/settings?fail=1");

    await page.getByLabel("Identifiant").fill("acme-2");
    await page.getByTestId("settings-save").click();

    await expect(page.getByText("Cet identifiant est déjà utilisé.")).toBeVisible();
    // And the work that produced the error is still there to correct.
    await expect(page.getByLabel("Identifiant")).toHaveValue("acme-2");
  });

  test("asks before leaving a form that has been changed", async ({ page }) => {
    await signIn(page);
    await page.goto("/settings");

    await page.getByLabel("Nom du workspace").fill("Quelque chose d'autre");
    await page.getByTestId("nav-overview").click();

    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("Quitter sans enregistrer ?");

    await dialog.getByRole("button", { name: "Continuer l'édition" }).click();
    await expect(page).toHaveURL(/\/settings$/);
  });
});
