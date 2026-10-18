/**
 * « Demander une compétence » (LEKA-501): it opens a suggestion for LEKA's
 * team, not Nouvelle intention; what is asked is sent as written, optional
 * fields as none; received, said with its reference; the same one twice or
 * too many today said in words, the draft kept.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { ApiError } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const api = vi.hoisted(() => ({ send: vi.fn() }));
vi.mock("@/lib/suggestions", () => ({ suggestions: api }));

const { SuggestCapability } = await import("@/components/capabilities/suggestion-dialog");

const show = () =>
  render(
    <LocaleProvider>
      <ConfirmProvider>
        <SuggestCapability />
      </ConfirmProvider>
    </LocaleProvider>,
  );

async function fill(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("catalogue-ask"));
  await screen.findByTestId("suggestion-dialog");
  await user.type(screen.getByLabelText("Compétence ou agent souhaité"), "Agent FinOps");
  await user.type(screen.getByLabelText("Le problème à résoudre"), "Nos factures cloud montent.");
  await user.type(screen.getByLabelText("Le cas d'usage"), "Chaque lundi, le service qui coûte plus.");
  await user.click(screen.getByTestId("suggestion-send"));
}

beforeEach(() => api.send.mockReset());

describe("Demander une compétence", () => {
  it("sends what was asked, the optional as none, and says it received", async () => {
    api.send.mockResolvedValue({ id: "s-1", status: "received" });
    const user = userEvent.setup();
    show();
    await fill(user);

    await waitFor(() =>
      expect(api.send).toHaveBeenCalledWith({
        name: "Agent FinOps",
        problem: "Nos factures cloud montent.",
        use_case: "Chaque lundi, le service qui coûte plus.",
        systems: null,
        context: null,
      }),
    );
    expect(await screen.findByTestId("suggestion-sent")).toHaveTextContent("Demande reçue");
    expect(screen.getByTestId("suggestion-sent")).toHaveTextContent("s-1");
  });

  it("the same one still open, or too many today: said, the draft kept", async () => {
    api.send.mockRejectedValueOnce(new ApiError(409, "/capability-suggestions", "dup", "conflict"));
    const user = userEvent.setup();
    show();
    await fill(user);
    expect(await screen.findByText(/déjà demandée dans votre espace/)).toBeInTheDocument();
    expect(screen.getByLabelText("Compétence ou agent souhaité")).toHaveValue("Agent FinOps");

    api.send.mockRejectedValueOnce(new ApiError(429, "/capability-suggestions", "many", "rate_limited"));
    await user.click(screen.getByTestId("suggestion-send"));
    expect(await screen.findByText(/cinq demandes aujourd'hui/)).toBeInTheDocument();
  });

  it("refuses too short a request before sending it", async () => {
    const user = userEvent.setup();
    show();
    await user.click(screen.getByTestId("catalogue-ask"));
    await user.type(await screen.findByLabelText("Compétence ou agent souhaité"), "AB");
    await user.click(screen.getByTestId("suggestion-send"));
    expect(api.send).not.toHaveBeenCalled();
  });
});
