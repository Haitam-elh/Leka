import { expect, test } from "@playwright/test";

import { signIn } from "./sign-in";

/**
 * An alert set on Mon environnement (LEKA-477), end to end on the demo
 * company: offered on what a source reads — payment-api, Datadog watching
 * it —, saved by the server, found where the screen's settings are, tried.
 */

test.describe("alert rules", () => {
  test("set from the screen's head, kept, tried", async ({ page }) => {
    await signIn(page);
    await page.goto("/environment");
    await page.getByTestId("alert-create").click();
    const dialog = page.getByTestId("alert-dialog");
    await expect(dialog).toBeVisible();
    // Never a channel said ready that is not: Slack, coming.
    // Slack: connected by its webhook, here not yet (LEKA-496); SMS never offered.
    await expect(dialog.getByTestId("alert-channel-slack")).toHaveAttribute("data-status", "not_connected");
    await expect(dialog.getByTestId("alert-channel-sms")).toHaveAttribute("data-status", "unavailable");

    await dialog.getByTestId("alert-subject").click();
    await page.getByRole("option", { name: "payment-api", exact: true }).click();
    await expect(dialog.getByTestId("alert-subject")).toContainText("payment-api");
    const name = `payment-api en panne ${Date.now()}`;
    await dialog.getByLabel("Nom").fill(name);
    await dialog.getByTestId("alert-save").click();
    await expect(dialog).toBeHidden();

    await page.goto("/environment?tab=configuration");
    const rule = page.getByTestId("alert-rule").filter({ hasText: name });
    await expect(rule).toContainText("payment-api");
    await expect(rule.getByTestId("alert-rule-last")).toContainText("Jamais déclenchée");
    await rule.getByRole("button", { name: "Tester" }).click();
    await expect(rule.getByTestId("alert-rule-last")).toContainText("Dernier envoi");
  });
});
