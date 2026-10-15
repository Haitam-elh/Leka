import { expect, test } from "@playwright/test";

import { analyse, ask } from "./intention-helpers";
import { signIn } from "./sign-in";

/**
 * Every request through its five steps (2026-10-14, the product call:
 * « les 5 ronds doivent être utilisés », « il faut que j'aie la possibilité
 * de demander un agent après le résultat »).
 *
 * What this protects, in a browser: a question answered shows the plan and
 * the agents it takes; its decision is open — never « Non nécessaire » — and
 * nothing is launched without the person; « Je m'arrête là » takes it to
 * its Action step, the plan to tick off and download.
 */

test("a question answered is decided, then done by hand, its plan in hand", async ({ page }) => {
  await signIn(page);
  const id = await ask(page, `Qui est responsable d'auth-service ? (${Date.now()})`);
  analyse(id);

  await page.goto(`/intentions/${id}/results`);
  const proposal = page.getByTestId("intention-proposal");
  await expect(proposal.getByTestId("plan-step")).toHaveCount(3);
  await expect(page.getByTestId("intention-step-decision")).not.toContainText("Non nécessaire");
  await page.getByTestId("results-to-decision").click();

  await expect(page).toHaveURL(new RegExp(`/intentions/${id}/decision$`));
  const decide = page.getByTestId("agents-decision");
  await expect(decide).toContainText("Comment voulez-vous le faire ?");
  await expect(decide.getByTestId("decide-launch")).toBeDisabled();
  await decide.getByTestId("decide-by-hand").click();

  await expect(page).toHaveURL(new RegExp(`/intentions/${id}/actions$`));
  const checks = page.getByTestId("plan-check");
  await expect(checks).toHaveCount(3);
  await checks.first().click();
  await expect(checks.first()).toHaveAttribute("aria-checked", "true");
  await expect(page.getByTestId("plan-download")).toBeVisible();
  await expect(page.getByTestId("intention-step-action")).toHaveAttribute("data-state", "done");
});
