import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * The home's paperclip, in a real browser.
 *
 * What these protect:
 * - The paperclip opens the file picker, from the keyboard too; a file LEKA
 *   reads is sent and said attached; one it does not read is refused and
 *   said why, never sent; one removed before asking is gone.
 * - Asked, the intention carries its files: its page lists them, and they
 *   are read back from there.
 * - A network cut is said and tried again, the words kept; a file past the
 *   limit is refused before it travels.
 */

const ASKED = "Pourquoi l'API de paiement est-elle plus lente depuis hier ?";
const NOTES = "p99 à 2,1 s depuis le déploiement v2.8.4\n";

test.describe("The home's paperclip", () => {
  test("files chosen from the keyboard, the refused one said, the kept one on the intention's page", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto("/overview");
    await page.getByTestId("intention-input").fill(ASKED);

    // The picker, opened from the keyboard.
    await page.getByTestId("attachment-pick").focus();
    const chooser = page.waitForEvent("filechooser");
    await page.keyboard.press("Enter");
    await (
      await chooser
    ).setFiles([
      { name: "lenteurs.txt", mimeType: "text/plain", buffer: Buffer.from(NOTES) },
      { name: "outil.exe", mimeType: "application/x-msdownload", buffer: Buffer.from("MZ") },
    ]);

    const chips = page.getByTestId("attachment");
    const notes = chips.filter({ hasText: "lenteurs.txt" });
    const tool = chips.filter({ hasText: "outil.exe" });
    await expect(notes).toHaveAttribute("data-status", "kept");
    await expect(notes).toContainText("Texte");
    await expect(tool).toHaveAttribute("data-status", "refused");
    await expect(tool).toContainText("Format non pris en charge");
    // Removed before asking.
    await page.getByRole("button", { name: "Retirer outil.exe" }).click();
    await expect(chips).toHaveCount(1);

    await page.getByTestId("intention-submit").click();
    await expect(page).toHaveURL(/\/intentions\/[0-9a-f-]{36}/);
    const attached = page.getByTestId("detail-attachment");
    await expect(attached).toHaveCount(1);
    await expect(attached).toContainText("lenteurs.txt");
    // Read back from its page, by whoever reads the intention.
    const read = await page.request.get((await attached.getAttribute("href")) ?? "");
    expect(read.status()).toBe(200);
    expect(await read.text()).toBe(NOTES);
  });

  test("a network cut said and tried again, the words kept; too large, refused before it travels", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto("/overview");
    await page.getByTestId("intention-input").fill(ASKED);

    let cut = true;
    await page.route("**/api/v1/intentions/attachments", (route) =>
      cut ? route.abort("internetdisconnected") : route.continue(),
    );
    await page.getByTestId("attachment-input").setInputFiles({
      name: "lenteurs.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(NOTES),
    });
    const chip = page.getByTestId("attachment");
    await expect(chip).toHaveAttribute("data-status", "failed");
    await expect(chip).toContainText("Connexion interrompue.");
    // Nothing asked while a file is not kept: the words are still there.
    cut = false;
    await chip.getByTestId("attachment-retry").click();
    await expect(chip).toHaveAttribute("data-status", "kept");
    await expect(page.getByTestId("intention-input")).toHaveValue(ASKED);

    await page.getByTestId("attachment-input").setInputFiles({
      name: "trace.json",
      mimeType: "application/json",
      buffer: Buffer.alloc(11 * 1024 * 1024, 32),
    });
    const big = page.getByTestId("attachment").filter({ hasText: "trace.json" });
    await expect(big).toHaveAttribute("data-status", "refused");
    await expect(big).toContainText("Trop volumineux : 10 Mo au maximum.");
  });
});
