/**
 * Asking before doing.
 *
 * What these protect is the keyboard, which is where a confirmation dialog
 * is either a safety net or a trap: where focus starts, what Escape means,
 * and where focus goes back to. A destructive button that is one stray
 * Enter away is worse than no dialog at all, because it looks careful.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConfirmProvider, useConfirm } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const DESTRUCTIVE = {
  title: "Supprimer la source ?",
  description: "Son historique sera perdu.",
  confirmLabel: "Supprimer la source",
  destructive: true,
  impact: ["3 services concernés", "Rollback indisponible"],
} as const;

function mount(options: Record<string, unknown> = DESTRUCTIVE) {
  const answered = vi.fn();

  function Trigger() {
    const confirm = useConfirm();
    return (
      <button
        type="button"
        onClick={() => void confirm(options as never).then(answered)}
      >
        Ouvrir
      </button>
    );
  }

  render(
    <LocaleProvider>
      <ConfirmProvider>
        <Trigger />
      </ConfirmProvider>
    </LocaleProvider>,
  );
  return { answered, opener: screen.getByRole("button", { name: "Ouvrir" }) };
}

describe("useConfirm", () => {
  it("resolves true when the action is confirmed", async () => {
    const user = userEvent.setup();
    const { answered, opener } = mount({
      title: "Lancer l'analyse ?",
      confirmLabel: "Lancer l'analyse",
    });

    await user.click(opener);
    await user.click(await screen.findByRole("button", { name: "Lancer l'analyse" }));

    await waitFor(() => expect(answered).toHaveBeenCalledWith(true));
  });

  it("resolves false when it is cancelled", async () => {
    const user = userEvent.setup();
    const { answered, opener } = mount({
      title: "Lancer l'analyse ?",
      confirmLabel: "Lancer l'analyse",
    });

    await user.click(opener);
    await user.click(await screen.findByRole("button", { name: "Annuler" }));

    await waitFor(() => expect(answered).toHaveBeenCalledWith(false));
  });

  it("resolves false on Escape, so nothing awaits for ever", async () => {
    const user = userEvent.setup();
    const { answered, opener } = mount();

    await user.click(opener);
    await screen.findByRole("alertdialog");
    await user.keyboard("{Escape}");

    await waitFor(() => expect(answered).toHaveBeenCalledWith(false));
  });

  it("gives the keyboard back to whatever opened it", async () => {
    const user = userEvent.setup();
    const { opener } = mount();

    await user.click(opener);
    await screen.findByRole("alertdialog");
    await user.keyboard("{Escape}");

    await waitFor(() => expect(opener).toHaveFocus());
  });
});

describe("a destructive confirmation", () => {
  it("starts with focus on Annuler, not on the red button", async () => {
    const user = userEvent.setup();
    const { opener } = mount();

    await user.click(opener);

    // The whole point: Enter, pressed by reflex, must cancel.
    await waitFor(() => expect(screen.getByRole("button", { name: "Annuler" })).toHaveFocus());
  });

  it("shows what the action will affect", async () => {
    const user = userEvent.setup();
    const { opener } = mount();

    await user.click(opener);

    expect(await screen.findByText("3 services concernés")).toBeInTheDocument();
    expect(screen.getByText("Rollback indisponible")).toBeInTheDocument();
  });

  it("keeps the button refused until the name is typed exactly", async () => {
    const user = userEvent.setup();
    const { answered, opener } = mount({
      ...DESTRUCTIVE,
      requireTypedConfirmation: "payment-api",
    });

    await user.click(opener);
    const action = await screen.findByRole("button", { name: "Supprimer la source" });
    expect(action).toBeDisabled();

    const box = screen.getByRole("textbox");
    await user.type(box, "payment-ap");
    expect(action).toBeDisabled();

    await user.type(box, "i");
    await waitFor(() => expect(action).toBeEnabled());

    await user.click(action);
    await waitFor(() => expect(answered).toHaveBeenCalledWith(true));
  });
});
