import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { MODEL_ENV } from "./model-env";
import { pythonExecutable, repositoryRoot } from "./python";
import { signIn } from "./sign-in";

/**
 * An agent's product page, in a real browser (LEKA-471).
 *
 * What these protect:
 * - From the catalogue to an agent: its promise, its price and its state as
 *   the server says them, its sections by their address — and the way to
 *   use it, then to give it a request.
 * - A section opened by its address, the page loaded on it.
 * - Every agent on sale has its page, the same structure for each.
 * - The action follows the state: an option to buy on Starter, for whoever
 *   may; a plan first on Free; a run form only where it may run.
 * - On a laptop, the mockup's two columns; on a phone, how to get it right
 *   under the hero — never wider than the screen.
 */

function run(lines: string[], ...args: string[]): void {
  execFileSync(pythonExecutable(), ["-c", lines.join("\n"), ...args], {
    cwd: path.join(repositoryRoot(), "api"),
    stdio: "inherit",
    env: { ...process.env, ...MODEL_ENV },
  });
}

/** The demo workspace on a plan — LEKA's grant taken back, or given again. */
function onPlan(plan: string, granted: boolean): void {
  run(
    [
      "import asyncio, sys",
      "from sqlalchemy import select",
      "from leka.db import session_factory, system_scope, workspace_scope",
      "from leka.platform import Workspace",
      "from leka.billing import end, grant",
      "from leka.billing.entitlements import EVERY",
      "from leka.governance import set_plan",
      "async def main(plan, granted):",
      "    with system_scope():",
      "        async with session_factory() as session:",
      "            ws = await session.scalar(select(Workspace).where(Workspace.slug == 'acme'))",
      "    with workspace_scope(ws.id):",
      "        async with session_factory() as session:",
      "            await set_plan(session, ws.id, plan, by='e2e', reason='LEKA-471')",
      "            if granted == '1':",
      "                await grant(session, ws.id, by='e2e', reason='LEKA-471')",
      "            else:",
      "                await end(session, ws.id, key=EVERY)",
      "            await session.commit()",
      "asyncio.run(main(sys.argv[1], sys.argv[2]))",
    ],
    plan,
    granted ? "1" : "0",
  );
}

const choose = (page: Page) => page.getByTestId("agent-choose").getByTestId("agent-cta");

test.describe("An agent's product page", () => {
  test.use({ viewport: { width: 1536, height: 1024 } });

  test("from the catalogue: its promise, price and state, its sections — used, then given a request", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto("/capabilities");
    await page
      .locator('[data-testid="capability-card"][data-key="application-architecture"]')
      .getByRole("link", { name: "Architecte applicatif" })
      .click();
    await expect(page).toHaveURL(/\/capabilities\/application-architecture$/);
    await expect(page.getByTestId("capability")).toHaveAttribute("data-page", "product");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Architecte applicatif");
    await expect(page.getByTestId("agent-promise")).toContainText("Le dossier d'architecture d'un parcours métier");
    // The server's facts: its price, the plan that includes it, its state.
    const hero = page.getByTestId("agent-hero");
    await expect(page.getByTestId("agent-hero-price")).toContainText(/25\s€/);
    await expect(hero).toContainText("Inclus dès Business");
    await expect(hero.getByTestId("agent-state")).toHaveText("Inclus dans votre plan");
    await expect(page.getByTestId("agent-plans")).toContainText("Enterprise");

    // Its sections, by their address.
    const faq = page.getByTestId("agent-tabs").getByRole("link", { name: "FAQ" });
    await faq.click();
    await expect(page).toHaveURL(/#faq$/);
    await expect(page.getByTestId("agent-faq")).toBeInViewport();
    await expect(faq).toHaveAttribute("aria-current", "location");

    // Included, here, and able to run: used from its page.
    await expect(choose(page)).toHaveText("Utiliser l'agent");
    await choose(page).click();
    await expect(page).toHaveURL(/#use$/);
    await expect(page.getByTestId("agent-run-form")).toBeInViewport();

    // A use case, given to it as a request.
    await page.getByTestId("agent-use-case").first().getByTestId("agent-ask").click();
    await expect(page).toHaveURL(/\/intentions\/new\?q=/);
    await expect(page.getByTestId("intention-input")).toHaveValue(
      "Construis l'architecture du parcours Paiement CB sur le périmètre Digital",
    );
  });

  test("a section opened by its address", async ({ page }) => {
    await signIn(page);
    await page.goto("/capabilities/code-review#use-cases");
    await expect(page.getByTestId("agent-use-cases")).toBeInViewport();
    await expect(page.getByTestId("agent-use-case")).toHaveCount(4);
    await page.goto("/capabilities/code-review#pricing");
    await expect(page.getByTestId("agent-pricing")).toBeInViewport();
  });

  test("every agent on sale has its page, the same for each", async ({ page }) => {
    test.setTimeout(360_000);
    // A dozen API calls a page, against the API's backstop of 300 a minute
    // per session (api/leka/api/ratelimit.py): past twenty-odd agents the
    // walk was refused (429) and a page said it could not show. As a client
    // should, it reads what is left of the window and waits for its reset.
    let left = Number.POSITIVE_INFINITY;
    let reset = 0;
    page.on("response", (response) => {
      const said = response.headers()["ratelimit-remaining"];
      if (said === undefined) return;
      left = Number(said);
      reset = Number(response.headers()["ratelimit-reset"] ?? "0");
    });
    await signIn(page);
    // What the server sells — its own list, never the screen's.
    const keys = await page.evaluate(async (api) => {
      const response = await fetch(`${api}/api/v1/billing/add-ons`, { credentials: "include" });
      const sold = (await response.json()) as { agents: { key: string; why: string | null }[] };
      return sold.agents.filter((agent) => agent.why !== "not_for_sale").map((agent) => agent.key);
    }, process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000");
    expect(keys.length).toBeGreaterThan(20);
    for (const key of keys) {
      if (left < 40) {
        await page.waitForTimeout((reset + 1) * 1000);
        left = Number.POSITIVE_INFINITY;
      }
      await page.goto(`/capabilities/${key}`);
      await expect(page.getByTestId("capability"), key).toHaveAttribute("data-page", "product");
      // Its product, never the registry's English first.
      await expect(page.getByTestId("agent-promise"), key).not.toContainText("Use when");
      await expect(page.getByTestId("agent-benefit"), key).toHaveCount(3);
      await expect(page.getByTestId("agent-use-case"), key).toHaveCount(4);
      await expect(page.getByTestId("agent-example"), key).toHaveCount(2);
      await expect(choose(page), key).toBeVisible();
    }
  });
});

test.describe("The action its state allows", () => {
  test.use({ viewport: { width: 1536, height: 1024 } });
  // The demo as the seed leaves it — on Business, LEKA's grant given — for
  // the specs after this one.
  test.afterEach(() => onPlan("business", true));

  test("an option to buy on Starter, for whoever may; a plan first on Free", async ({ page }) => {
    test.setTimeout(120_000);
    onPlan("starter", false);
    await signIn(page);
    // Enterprise includes it; Starter sells it as an option.
    await page.goto("/capabilities/design-review");
    await expect(choose(page)).toHaveAttribute("data-cta", "buy");
    await expect(choose(page)).toBeEnabled();
    await expect(page.getByTestId("agent-hero").getByTestId("agent-state")).toHaveText("Option payante");
    await expect(page.locator('[data-testid="agent-plans-table"] tr[data-plan="starter"]')).toContainText(
      "En option",
    );
    await expect(page.locator('[data-testid="agent-plans-table"] tr[data-plan="enterprise"]')).toContainText(
      "Inclus",
    );
    // Not bought: no run form.
    await expect(page.getByTestId("agent-use")).toHaveCount(0);

    onPlan("free", false);
    await page.reload();
    await expect(choose(page)).toHaveAttribute("data-cta", "upgrade");
    await expect(page.getByTestId("agent-choose")).toContainText(
      "Les agents sont disponibles à partir de la formule Starter.",
    );
    await choose(page).click();
    await expect(page).toHaveURL(/\/billing\/plans$/);
  });
});

test.describe("On a laptop", () => {
  test.use({ viewport: { width: 1024, height: 768 } });

  test("the mockup's two columns: the page, and how to get it beside it", async ({ page }) => {
    await signIn(page);
    await page.goto("/capabilities/application-architecture");
    const side = page.getByTestId("agent-choose");
    await expect(side).toBeVisible();
    await expect(page.getByTestId("agent-choose-top")).toBeHidden();
    const main = await page.getByTestId("agent-hero").boundingBox();
    const beside = await side.boundingBox();
    expect(beside!.x).toBeGreaterThan(main!.x + main!.width);
    expect(
      await page.evaluate(() => {
        const content = document.querySelector("#main-content") as HTMLElement;
        return content.scrollWidth - content.clientWidth;
      }),
    ).toBeLessThanOrEqual(0);
  });
});

test.describe("On a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("how to get it right under the hero, nothing wider than the screen", async ({ page }) => {
    await signIn(page);
    await page.goto("/capabilities/application-architecture");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Architecte applicatif");
    const top = page.getByTestId("agent-choose-top");
    await expect(top).toBeVisible();
    await expect(page.getByTestId("agent-choose")).toBeHidden();
    const hero = await page.getByTestId("agent-hero").boundingBox();
    const card = await top.boundingBox();
    expect(card!.y).toBeGreaterThan(hero!.y + hero!.height - 1);
    expect(
      await page.evaluate(() => {
        const content = document.querySelector("#main-content") as HTMLElement;
        return content.scrollWidth - content.clientWidth;
      }),
    ).toBeLessThanOrEqual(0);
  });
});
