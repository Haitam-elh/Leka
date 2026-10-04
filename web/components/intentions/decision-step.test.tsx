/**
 * The decision step (LEKA-341): LEKA's proposals, chosen and approved.
 *
 * What these protect: the screen says, before anything else, that its
 * recommendations are an example; each is a proposal — drawn as one, apart
 * from facts — with why, what it would change, how risky, whether it can
 * be undone, how sure LEKA is; choosing one brings the actions; approving
 * says what it will affect before it does.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { DecisionStep } = await import("@/components/intentions/decision-step");

function show() {
  return render(
    <LocaleProvider>
      <ConfirmProvider>
        <DecisionStep />
      </ConfirmProvider>
    </LocaleProvider>,
  );
}

describe("the decision step", () => {
  it("says its recommendations are an example, and draws each as a proposal", () => {
    show();

    const proposals = screen.getByRole("region", { name: "Recommandations" });
    expect(proposals).toHaveTextContent("Proposition de LEKA");
    expect(within(proposals).getByTestId("example-notice")).toHaveTextContent("Exemple");
    const cards = within(proposals).getAllByTestId("recommendation");
    expect(cards).toHaveLength(3);
    expect(cards[0]).toHaveTextContent("Revenir à payment-api v2.8.3");
    expect(cards[0]).toHaveTextContent("Effet : 3 services concernés");
    expect(cards[0]).toHaveTextContent("Risque moyen");
    expect(cards[0]).toHaveTextContent("Réversible");
    expect(cards[0]).toHaveTextContent("Confiance moyenne · 82 %");
  });

  it("brings the actions when one is chosen, and says what approving affects", async () => {
    const user = userEvent.setup();
    show();

    expect(screen.queryByRole("region", { name: "Actions sur la sélection" })).toBeNull();
    await user.click(screen.getByRole("checkbox", { name: "Revenir à payment-api v2.8.3" }));
    expect(screen.getByRole("region", { name: "Actions sur la sélection" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Valider et passer à l'action" }));
    expect(await screen.findByRole("alertdialog")).toHaveTextContent("3 services concernés");
  });
});
