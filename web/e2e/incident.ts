import { expect, type Page } from "@playwright/test";

import { signIn } from "./sign-in";

/** The demo's incident (scripts/seed.py), its sheet open on its analysis. */
export async function openIncident(page: Page) {
  await signIn(page);
  await page.keyboard.press("ControlOrMeta+k");
  await page.getByTestId("palette-input").fill("p99 latency");
  await page.getByRole("option", { name: /^payment-api p99 latency above 2s/ }).click();
  await expect(page).toHaveURL(/\/environment\/incidents\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("incident-analysis")).toBeVisible();
}
