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

  await page.goto("/register");
  await page.getByLabel("Adresse e-mail", { exact: true }).fill(email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Créer le compte" }).click();
  await expect(page.getByText("Consultez votre boîte de réception")).toBeVisible();

  const link = await linkFromEmail(email, "Confirmez votre adresse e-mail LEKA");
  expect(link.origin).toBe("http://localhost:3000");
  await page.goto(link.href);
  await expect(page.getByText("Adresse confirmée")).toBeVisible();

  await signIn(page, email, PASSWORD);
});

test("a forgotten password is reset from its email", async ({ page }) => {
  const email = `e2e-${Date.now()}@leka.example`;
  await page.goto("/register");
  await page.getByLabel("Adresse e-mail", { exact: true }).fill(email);
  await page.getByLabel("Mot de passe", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Créer le compte" }).click();
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
