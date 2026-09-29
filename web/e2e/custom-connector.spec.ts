import { createHmac } from "node:crypto";

import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * A tool LEKA has no connector for, connected through the Sources screen
 * alone (LEKA-426) — in a browser, against the real API.
 *
 * "Helpdesk", an in-house ticketing tool, sends its changes by webhook:
 * the admin starts from "Connecteur sur mesure", picks the method, starts
 * the definition from the example, tests, activates, gives the address to
 * the tool — played here by the test — and sees each delivery arrive on the
 * source's page. A delivery stays "En attente": no worker runs in this
 * suite, and what a pass does with it is the API's tests' (LEKA-350).
 *
 * The source is deleted at the end, through the screen as well: the suite
 * runs again on the same database.
 */

const SECRET = "helpdesk-hooks-e2e-shared-secret";

test("a custom connector goes from the Sources screen to deliveries received", async ({
  page,
  playwright,
}) => {
  const name = `Helpdesk ${Date.now()}`;
  await signIn(page);
  await page.goto("/sources");

  await page.getByRole("button", { name: "Connecteur sur mesure" }).click();
  const dialog = page.getByRole("dialog", { name: "Connecteur sur mesure" });
  await expect(dialog.getByText("Pas pris en charge aujourd'hui")).toBeVisible();
  await dialog.getByRole("button", { name: /Webhook entrant/ }).click();

  await dialog.getByLabel("Nom de la source").fill(name);
  await dialog.getByLabel(/^Secret/).fill(SECRET);
  await dialog.getByRole("button", { name: "Partir d'un exemple" }).click();
  await dialog.getByRole("button", { name: "Enregistrer et continuer" }).click();

  await expect(dialog.getByText("Connexion réussie")).toBeVisible();
  const shown = dialog.getByText(/\/api\/v1\/webhooks\/sources\/[0-9a-f-]{36}$/);
  const address = (await shown.textContent())?.trim() ?? "";
  const sourceId = address.split("/").at(-1) ?? "";
  expect(sourceId).toHaveLength(36);
  await dialog.getByRole("button", { name: "Activer la source" }).click();
  await expect(dialog).toBeHidden();

  // The tool sends — from outside the browser, with no session of LEKA's:
  // unsigned first, which is refused and leaves nothing.
  const tool = await playwright.request.newContext();
  const delivery = JSON.stringify({
    event: "ticket.updated",
    ticket: { id: 101, subject: "VPN drops every hour", status: "Open" },
  });
  const unsigned = await tool.post(address, {
    data: delivery,
    headers: { "Content-Type": "application/json" },
  });
  expect(unsigned.status()).toBe(401);
  const signature = createHmac("sha256", SECRET).update(delivery).digest("hex");
  const signed = await tool.post(address, {
    data: delivery,
    headers: { "Content-Type": "application/json", "X-Leka-Signature": `sha256=${signature}` },
  });
  expect(signed.status(), await signed.text()).toBe(202);
  expect((await signed.json()).status).toBe("pending");
  await tool.dispose();

  // A normal source, which says it is custom, and shows what it received.
  await page.goto(`/sources/${sourceId}`);
  await expect(page.getByRole("heading", { level: 1, name })).toBeVisible();
  await expect(page.getByText("Sur mesure").first()).toBeVisible();
  const reception = page.locator("section", {
    has: page.getByRole("heading", { name: "Réception" }),
  });
  await expect(reception.getByText(address)).toBeVisible();
  const row = reception.getByRole("row").nth(1);
  await expect(row).toContainText("En attente");
  await expect(row).toContainText("tickets");

  await page.getByRole("button", { name: "Supprimer" }).click();
  await page.getByLabel(`Pour confirmer, saisissez ${name}`).fill(name);
  await page.getByRole("button", { name: "Supprimer la source" }).click();
  await expect(page).toHaveURL(/\/sources$/);
});
