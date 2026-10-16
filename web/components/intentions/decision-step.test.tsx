/**
 * The decision step (LEKA-341), as mockup 05 lays it out: LEKA's proposals,
 * chosen and approved.
 *
 * What these protect: the screen says, before anything else, that what it
 * shows is an example; each recommendation is a card to tick — its
 * priority, what it touches, how long, whether it can be undone, how risky,
 * how sure LEKA is — opening on what justifies it, each piece of which
 * says it is an example; beside them what they rest on — the impact, the
 * confidence and what that rests on, the next steps; nothing runs without
 * a yes, and it says so; choosing one brings the actions; approving says
 * what it will affect before it does.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { DecisionStep } = await import("@/components/intentions/decision-step");
const { notify } = await import("@/lib/notify");

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
  it("says first that it is an example, then draws each recommendation as a card to choose", () => {
    show();

    const notice = screen.getByTestId("example-notice");
    const proposals = screen.getByRole("region", { name: "Recommandations de LEKA" });
    // The notice comes before anything it qualifies.
    expect(
      notice.compareDocumentPosition(proposals) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(notice).toHaveTextContent("Cette étape est un exemple");
    expect(proposals).toHaveTextContent("3 recommandations");
    expect(proposals).toHaveTextContent("Sélectionnez les actions");

    const cards = within(proposals).getAllByTestId("recommendation");
    expect(cards.map((card) => card.dataset.priority)).toEqual(["high", "medium", "low"]);
    expect(cards[0]).toHaveTextContent("Revenir à payment-api v2.8.3");
    expect(cards[0]).toHaveTextContent("Priorité haute");
    expect(cards[0]).toHaveTextContent("Impact : 3 services concernés");
    expect(cards[0]).toHaveTextContent("≈ 15 min");
    expect(cards[0]).toHaveTextContent("Réversible");
    expect(cards[0]).toHaveTextContent("Risque moyen");
    expect(within(cards[0]).getByTestId("confidence")).toHaveTextContent("Confiance moyenne82 %");
    expect(within(cards[0]).getByRole("checkbox")).not.toBeChecked();
  });

  it("opens on what justifies a recommendation, each piece said to be an example", async () => {
    const user = userEvent.setup();
    show();

    await user.click(
      screen.getByRole("button", { name: "Voir ce qui justifie « Revenir à payment-api v2.8.3 »" }),
    );
    const strip = screen.getByTestId("evidence-strip");
    expect(strip).toHaveTextContent("Éléments qui justifient cette recommandation");
    expect(strip).toHaveTextContent("Déploiement payment-api v2.8.4");
    expect(strip).toHaveTextContent("GitHub · Exemple");
  });

  it("says beside them what they rest on, and that nothing runs without a yes", () => {
    show();

    const aside = screen.getByRole("complementary", { name: "Ce qui fonde ces recommandations" });
    expect(within(aside).getByTestId("impact-level")).toHaveTextContent("Élevé");
    const confidence = within(aside).getByRole("region", { name: "Confiance de l'analyse" });
    expect(confidence).toHaveTextContent("Moyenne");
    expect(confidence).toHaveTextContent("D'autres sources pourraient affiner l'analyse");
    expect(within(aside).getByRole("region", { name: "Prochaines étapes" })).toHaveTextContent(
      "Valider les actions sélectionnées",
    );
    expect(screen.getByTestId("control-notice")).toHaveTextContent("Vous gardez le contrôle");
  });

  it("brings the actions when one is chosen, and says what approving affects", async () => {
    const user = userEvent.setup();
    show();

    expect(screen.queryByRole("region", { name: "Actions sur la sélection" })).toBeNull();
    await user.click(screen.getByRole("checkbox", { name: "Revenir à payment-api v2.8.3" }));
    expect(screen.getByRole("region", { name: "Actions sur la sélection" })).toBeVisible();
    expect(screen.getAllByTestId("recommendation")[0].className).toContain("border-state-danger");

    await user.click(screen.getByRole("button", { name: "Valider et passer à l'action" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("3 services concernés");
    // An example: it says nothing will be applied, then claims no success.
    expect(dialog).toHaveTextContent("rien ne sera appliqué");
    await user.click(within(dialog).getByRole("button", { name: "Valider et passer à l'action" }));
    expect(await screen.findByTestId("decision-settled")).toHaveTextContent("aucune action n'a été envoyée");
    expect(notify.success).not.toHaveBeenCalled();
  });
});
