import { expect, test } from "@playwright/test";

import { linkFromEmail } from "./outbox";
import { expectSignedIn, loginAnswer } from "./sign-in";

/**
 * From the inbox to a signed-in session, as a new person would go (LEKA-330).
 *
 * What broke in front of a user: the links in these emails were relative
 * API paths — "/auth/verify/<token>" — with no domain and no page behind
 * them. Every other test used the seeded account and never needed an email,
 * so nothing ever clicked one. These do: the link is taken from the email
 * and opened as it is.
 */

const PASSWORD = "a long enough passphrase";

/** The registration form, as someone arriving from leka-core.com fills it:
 * what it requires, and nothing it leaves optional. */
async function register(page: import("@playwright/test").Page, email: string) {
  await page.goto("/register");
  await page.getByLabel("Prénom", { exact: true }).fill("Nora");
  await page.getByLabel("Nom", { exact: true }).fill("Diallo");
  await page.getByLabel("Entreprise", { exact: true }).fill("Acme");
  await page.getByLabel("E-mail professionnel", { exact: true }).fill(email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Créer le compte" }).click();
}

async function signIn(page: import("@playwright/test").Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Adresse e-mail", { exact: true }).fill(email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(password);
  const answered = loginAnswer(page);
  await page.getByRole("button", { name: "Se connecter" }).click();
  expectSignedIn(await answered);
  await expect(page).not.toHaveURL(/\/login$/);
}

test("a new account is confirmed from its email, then signs in", async ({ page }) => {
  const email = `e2e-${Date.now()}@leka.example`;

  await register(page, email);
  await expect(page.getByText("Consultez votre boîte de réception")).toBeVisible();

  const link = await linkFromEmail(email, "Confirmez votre adresse e-mail LEKA");
  expect(link.origin).toBe("http://localhost:3000");
  await page.goto(link.href);
  await expect(page.getByText("Adresse confirmée")).toBeVisible();

  await signIn(page, email, PASSWORD);

  // A new account belongs to no workspace: it is asked to create one, named
  // after the company it gave, then which of its tools to connect.
  await expect(page.getByRole("heading", { name: "Créez votre espace de travail" })).toBeVisible();
  await expect(page.getByLabel("Nom de l'espace")).toHaveValue("Acme");
  await page.getByRole("button", { name: "Créer l'espace" }).click();
  await expect(page).toHaveURL(/\/welcome$/);
  await expect(page.getByRole("heading", { name: "Bienvenue sur LEKA" })).toBeVisible();
  await expect(page.getByTestId("nav-overview")).toBeVisible();

  // The tools chosen open the wizard at their connection, one by one.
  await page.getByRole("button", { name: /^GitHub/ }).click();
  await page.getByRole("button", { name: /^Splunk/ }).click();
  await expect(page.getByText("2 outil(s) choisi(s)")).toBeVisible();
  await page.getByRole("button", { name: "Connecter mes outils" }).click();
  const wizard = page.getByRole("dialog");
  await expect(wizard.getByLabel(/Token d'accès/)).toBeVisible();
  await wizard.getByRole("button", { name: "Fermer" }).click();
  await expect(page.getByText("0 sur 2 connecté(s)")).toBeVisible();
  await page.getByRole("link", { name: "Terminer" }).click();
  await expect(page).toHaveURL(/\/sources$/);
});

test("an account is closed from its profile, and cannot sign in again", async ({ page }) => {
  const email = `e2e-${Date.now()}@leka.example`;
  await register(page, email);
  await page.goto((await linkFromEmail(email, "Confirmez votre adresse e-mail LEKA")).href);
  await expect(page.getByText("Adresse confirmée")).toBeVisible();
  await signIn(page, email, PASSWORD);
  await page.getByRole("button", { name: "Créer l'espace" }).click();
  await expect(page).toHaveURL(/\/welcome$/);

  await page.getByTestId("user-menu").last().click();
  await page.getByTestId("profile").click();
  await page.getByRole("button", { name: "Supprimer mon compte…" }).click();
  await page.getByLabel("Votre mot de passe, pour confirmer").fill(PASSWORD);
  await page.getByRole("button", { name: "Supprimer définitivement" }).click();

  // Gone, signed out, back on the site.
  await expect(page).toHaveURL("http://localhost:3000/");
  await page.goto("/login");
  await page.getByLabel("Adresse e-mail", { exact: true }).fill(email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.locator('[data-slot="alert"]')).toHaveText(
    "Adresse e-mail ou mot de passe incorrect.",
  );
});

test("a forgotten password is reset from its email", async ({ page }) => {
  const email = `e2e-${Date.now()}@leka.example`;
  await register(page, email);
  await page.goto((await linkFromEmail(email, "Confirmez votre adresse e-mail LEKA")).href);
  await expect(page.getByText("Adresse confirmée")).toBeVisible();

  await page.goto("/forgot-password");
  await page.getByLabel("Adresse e-mail", { exact: true }).fill(email);
  await page.getByRole("button", { name: "Envoyer le lien" }).click();
  await expect(page.getByText("Consultez votre boîte de réception")).toBeVisible();

  const link = await linkFromEmail(email, "Réinitialisez votre mot de passe LEKA");
  expect(link.pathname).toBe("/reset-password");
  await page.goto(link.href);
  await page.getByLabel("Nouveau mot de passe", { exact: true }).fill(`${PASSWORD} renewed`);
  await page.getByRole("button", { name: "Enregistrer le mot de passe" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await signIn(page, email, `${PASSWORD} renewed`);
});
