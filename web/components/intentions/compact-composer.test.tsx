/**
 * The overview's box (2026-10-14: what was typed there was carried to
 * another screen to be asked again, and read as « ça ne marche pas »).
 *
 * What these protect: what is typed is asked from the box itself — every
 * source, every environment, no period nobody chose, one key per sentence —
 * and its page opens; a request about anything but technology is said in
 * words, above the box, and nothing opens.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { ApiError } from "@/lib/api";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentWorkspace: () => ({ id: "ws-1", name: "Acme", slug: "acme", role: "owner" }),
}));

const create = vi.fn();
vi.mock("@/lib/intentions/api", async (original) => ({
  ...(await original<typeof import("@/lib/intentions/api")>()),
  submitIntention: create,
}));

const { CompactIntentionComposer } = await import("@/components/intentions/compact-composer");

function renderIt() {
  render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <CompactIntentionComposer />
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

async function ask(words: string) {
  const user = userEvent.setup();
  await user.type(screen.getByPlaceholderText("Décrivez votre intention en langage naturel…"), words);
  await user.click(screen.getByTestId("intention-submit"));
}

describe("the overview's box", () => {
  beforeEach(() => {
    push.mockReset();
    create.mockReset();
  });

  it("asks what is typed, from the box, and opens its page", async () => {
    create.mockResolvedValue({ intention: { id: "int-1" }, context: {} });
    renderIt();
    await ask("Pourquoi payment-api est lente ?");

    await waitFor(() => expect(push).toHaveBeenCalledWith("/intentions/int-1"));
    const [asked, key] = create.mock.calls[0];
    // Every source, every environment, no period nobody chose.
    expect(asked).toMatchObject({ text: "Pourquoi payment-api est lente ?", sources: [], services: [] });
    expect(asked).not.toHaveProperty("environment");
    expect(asked).not.toHaveProperty("since");
    expect(typeof key).toBe("string");
  });

  it("says what LEKA answers about when the request is not about technology", async () => {
    create.mockRejectedValue(
      new ApiError(422, "/api/v1/intentions", "LEKA answers questions about your technology stack.", "off_topic"),
    );
    renderIt();
    await ask("Donne-moi une recette de tarte aux pommes");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "LEKA répond aux questions liées à votre stack technique",
    );
    expect(push).not.toHaveBeenCalled();
  });
});
