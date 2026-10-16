/**
 * The overview's box (2026-10-14: what was typed there was carried to
 * another screen to be asked again, and read as « ça ne marche pas »).
 *
 * What these protect: what is typed is asked from the box itself — every
 * source, every environment, no period nobody chose, one key per sentence —
 * and its page opens, the button busy meanwhile (seconds of silence read as
 * broken, LEKA-450); a request about anything but technology is said in
 * words, above the box, and nothing opens. Its files go with it — only
 * those kept; one that cannot be linked is said, the words and the files
 * kept for another try.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
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

const sent = vi.hoisted(() => ({ upload: vi.fn(), remove: vi.fn() }));
vi.mock("@/lib/intentions/attachments", async (original) => ({
  ...(await original<typeof import("@/lib/intentions/attachments")>()),
  uploadAttachment: sent.upload,
  removeAttachment: sent.remove,
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
    sent.upload.mockReset();
    sent.remove.mockReset();
    // The box keeps its draft across a page (sessionStorage): not across tests.
    window.sessionStorage.clear();
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

  it("is busy while the intention is created, never pressed twice", async () => {
    let done: (made: unknown) => void = () => {};
    create.mockReturnValue(new Promise((resolve) => (done = resolve)));
    renderIt();
    await ask("Pourquoi payment-api est lente ?");

    const button = screen.getByTestId("intention-submit");
    await waitFor(() => expect(button).toBeDisabled());
    expect(button).toHaveAttribute("aria-busy", "true");
    done({ intention: { id: "int-1" }, context: {} });
    await waitFor(() => expect(push).toHaveBeenCalledWith("/intentions/int-1"));
    expect(create).toHaveBeenCalledTimes(1);
  });

  it("its files go with it — only those kept — and are the intention's then", async () => {
    const user = userEvent.setup();
    sent.upload
      .mockResolvedValueOnce({ id: "a1", name: "notes.txt", content_type: "text/plain", size_bytes: 3, created_at: "" })
      .mockRejectedValueOnce(new ApiError(0, "/intentions/attachments", "Cannot reach the API"));
    create.mockResolvedValue({ intention: { id: "int-1" }, context: {} });
    renderIt();
    const input = screen.getByTestId("attachment-input") as HTMLInputElement;
    await user.upload(input, new File(["one"], "notes.txt", { type: "text/plain" }));
    await user.upload(input, new File(["two"], "lost.txt", { type: "text/plain" }));
    await waitFor(() =>
      expect(screen.getAllByTestId("attachment").map((c) => c.getAttribute("data-status"))).toEqual([
        "kept",
        "failed",
      ]),
    );
    await ask("Pourquoi payment-api est lente ?");

    await waitFor(() => expect(push).toHaveBeenCalledWith("/intentions/int-1"));
    // The failed one is never said attached: only the kept one's id.
    expect(create.mock.calls[0][0]).toMatchObject({ attachments: ["a1"] });
    expect(screen.queryAllByTestId("attachment")).toHaveLength(0);
    expect(sent.remove).not.toHaveBeenCalled();
  });

  it("a file that cannot be linked is said — the words and the files kept", async () => {
    const user = userEvent.setup();
    sent.upload.mockResolvedValue({ id: "a1", name: "notes.txt", content_type: "text/plain", size_bytes: 3, created_at: "" });
    create.mockRejectedValue(
      new ApiError(422, "/api/v1/intentions", "unknown", "validation_failed", { attachments: "attachment_unknown" }),
    );
    renderIt();
    await user.upload(
      screen.getByTestId("attachment-input") as HTMLInputElement,
      new File(["one"], "notes.txt", { type: "text/plain" }),
    );
    await waitFor(() => expect(screen.getByTestId("attachment")).toHaveAttribute("data-status", "kept"));
    await ask("Pourquoi payment-api est lente ?");

    expect(await screen.findByRole("alert")).toHaveTextContent("Une pièce jointe n'a pas pu être rattachée");
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByTestId("intention-input")).toHaveValue("Pourquoi payment-api est lente ?");
    expect(within(screen.getByTestId("attachments")).getByText("notes.txt")).toBeInTheDocument();
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
