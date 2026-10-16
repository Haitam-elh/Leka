import { expect, type Page, test } from "@playwright/test";

import { ask } from "./intention-helpers";
import { signIn } from "./sign-in";

/**
 * The notification centre, in a real browser (LEKA-476).
 *
 * What these protect:
 * - An intention asked is told to its asker: the bell counts it; opened,
 *   the panel says it in words and leads to it — opened, it is read.
 * - The centre: by category, the unread only, all read at once — the bell
 *   then says nothing unread; a category hidden is neither shown nor
 *   counted, and shown again.
 * - On a phone: the bell in the header, its panel inside the screen, the
 *   centre never wider than it.
 */

async function unread(page: Page): Promise<number> {
  const count = page.getByTestId("notifications-count");
  return (await count.count()) ? Number((await count.textContent())?.replace("+", "") ?? 0) : 0;
}

test.describe("The notification centre", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("an intention asked: counted by the bell, said in words, opened — then read", async ({ page }) => {
    await signIn(page);
    const words = `Qui maintient auth-service ? (${Date.now()})`;
    const id = await ask(page, words);

    await page.goto("/overview");
    const bell = page.getByTestId("notifications-bell");
    await expect(bell).toHaveAccessibleName(/^Notifications, \d+ non lues?$/);
    expect(await unread(page)).toBeGreaterThan(0);
    await bell.click();
    const panel = page.getByTestId("notifications-panel");
    const created = panel.getByTestId("notification").filter({ hasText: "Intention créée" }).filter({ hasText: words });
    await expect(created).toHaveAttribute("data-read", "false");
    await created.getByTestId("notification-open").click();
    await expect(page).toHaveURL(new RegExp(`/intentions/${id}$`));

    // Read now, on the centre too.
    await page.goto("/notifications");
    const row = page
      .getByTestId("notification")
      .filter({ hasText: "Intention créée" })
      .filter({ hasText: words });
    await expect(row).toHaveAttribute("data-read", "true");
  });

  test("by category, the unread only, all read at once, a category hidden then shown", async ({ page }) => {
    await signIn(page);
    await ask(page, `Qui est responsable de payment-api ? (${Date.now()})`);
    await page.goto("/notifications");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Notifications");

    // By category: only intentions.
    await page.getByRole("button", { name: "Intentions", exact: true }).click();
    const rows = page.getByTestId("notification");
    await expect(rows.first()).toBeVisible();
    for (const kind of await rows.evaluateAll((all) => all.map((r) => r.getAttribute("data-kind") ?? ""))) {
      expect(kind).toMatch(/^intention\./);
    }
    // The unread only, then all read at once: nothing unread is left.
    await page.getByRole("switch", { name: "Non lues" }).click();
    await expect(rows.first()).toHaveAttribute("data-read", "false");
    await page.getByRole("button", { name: "Toutes", exact: true }).click();
    await page.getByTestId("notifications-read-all").click();
    await expect(page.getByTestId("notifications-empty")).toContainText("Tout est lu.");
    await expect(page.getByTestId("notifications-count")).toHaveCount(0);
    await expect(page.getByTestId("notifications-bell")).toHaveAccessibleName("Notifications");

    // A category hidden: neither shown nor counted — then shown again.
    await page.getByRole("switch", { name: "Non lues" }).click();
    const preference = page.getByTestId("notification-preferences").getByRole("switch", { name: "Intentions" });
    await preference.click();
    await expect(preference).not.toBeChecked();
    await expect(page.getByTestId("notification").filter({ hasText: "Intention créée" })).toHaveCount(0);
    await preference.click();
    await expect(preference).toBeChecked();
    await expect(page.getByTestId("notification").filter({ hasText: "Intention créée" }).first()).toBeVisible();
  });
});

test.describe("On a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the bell in the header, its panel inside the screen, the centre never wider", async ({ page }) => {
    await signIn(page);
    await page.goto("/overview");
    await page.getByTestId("notifications-bell").click();
    const panel = page.getByTestId("notifications-panel");
    await expect(panel).toBeVisible();
    const box = await panel.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(390);
    await panel.getByTestId("notifications-see-all").click();
    await expect(page).toHaveURL(/\/notifications$/);
    expect(
      await page.evaluate(() => {
        const content = document.querySelector("#main-content") as HTMLElement;
        return content.scrollWidth - content.clientWidth;
      }),
    ).toBeLessThanOrEqual(0);
  });
});
