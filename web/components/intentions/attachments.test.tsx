/**
 * The home's paperclip: files attached to an intention as it is written.
 *
 * What these protect:
 * - The paperclip opens the file picker — by mouse and by keyboard.
 * - A file chosen is sent at once; while on its way it says so, then it is
 *   said attached with its name, its type and its size.
 * - Refused before it travels, and said why: a type LEKA does not read, a
 *   file past the limit, a sixth file.
 * - A network failure is said and tried again — the words written and the
 *   other files untouched; a refusal by the server is said, never retried.
 * - Removed before asking: gone — removed on the server once kept, let go
 *   on its way.
 * - Nothing is asked while a file is on its way.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Form } from "@/components/forms/form";
import { ConfirmProvider } from "@/components/interactions/confirm";
import { ApiError } from "@/lib/api";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { type IntentionDraft, intentionDraftSchema } from "@/lib/validation/intentions";

const fr = DICTIONARIES.fr;
const sent = vi.hoisted(() => ({ upload: vi.fn(), remove: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentWorkspace: () => ({ id: "ws-1", name: "Acme", slug: "acme", role: "owner" }),
}));
vi.mock("@/lib/intentions/attachments", async (original) => ({
  ...(await original<typeof import("@/lib/intentions/attachments")>()),
  uploadAttachment: sent.upload,
  removeAttachment: sent.remove,
}));

const { useAttachments } = await import("@/components/intentions/attachments");
const { IntentionComposer } = await import("@/components/intentions/intention-composer");

function mount() {
  function Harness() {
    const form = useLekaForm<IntentionDraft>({
      schema: intentionDraftSchema,
      defaultValues: { text: "" },
      onSubmit: vi.fn(),
    });
    const files = useAttachments();
    return (
      <Form form={form}>
        <IntentionComposer variant="compact" files={files} onSubmit={() => void form.submit()} />
      </Form>
    );
  }
  render(
    <LocaleProvider>
      <ConfirmProvider>
        <Harness />
      </ConfirmProvider>
    </LocaleProvider>,
  );
}

const input = () => screen.getByTestId("attachment-input") as HTMLInputElement;
const chips = () => screen.queryAllByTestId("attachment");

function kept(id: string, name: string, size = 1229) {
  return { id, name, content_type: "text/plain", size_bytes: size, created_at: "2026-10-16T10:00:00Z" };
}

/** An upload held until the test lets it answer. */
function held() {
  let answer: (value: unknown) => void = () => {};
  let fail: (error: unknown) => void = () => {};
  const promise = new Promise((resolve, reject) => {
    answer = resolve;
    fail = reject;
  });
  return { promise, answer, fail };
}

beforeEach(() => {
  sent.upload.mockReset();
  sent.remove.mockReset();
  sent.remove.mockResolvedValue(undefined);
});

describe("the home's paperclip", () => {
  it("opens the file picker — by mouse and by keyboard", async () => {
    const user = userEvent.setup();
    mount();
    const opened = vi.spyOn(input(), "click");
    const paperclip = screen.getByRole("button", { name: fr.composer.attach });
    await user.click(paperclip);
    expect(opened).toHaveBeenCalledTimes(1);
    paperclip.focus();
    await user.keyboard("{Enter}");
    await user.keyboard(" ");
    expect(opened).toHaveBeenCalledTimes(3);
  });

  it("sends a file at once, says it on its way, then attached with its name, type and size", async () => {
    const user = userEvent.setup();
    const upload = held();
    sent.upload.mockReturnValue(upload.promise);
    mount();
    const file = new File(["x".repeat(1229)], "notes.txt", { type: "text/plain" });
    await user.upload(input(), file);

    const [chip] = chips();
    expect(chip).toHaveAttribute("data-status", "uploading");
    expect(chip).toHaveTextContent(fr.composer.files.uploading);
    expect(sent.upload).toHaveBeenCalledWith(file, "text/plain", expect.any(AbortSignal));

    upload.answer(kept("a1", "notes.txt"));
    await waitFor(() => expect(chips()[0]).toHaveAttribute("data-status", "kept"));
    expect(chips()[0]).toHaveTextContent("notes.txt");
    expect(chips()[0]).toHaveTextContent(/Texte · 1,2\s?ko/);
  });

  it("a Markdown file a browser gives no type for is sent as Markdown", async () => {
    const user = userEvent.setup();
    sent.upload.mockResolvedValue(kept("a1", "README.md"));
    mount();
    // The picker's accept list lets the extension through; the type is said by it.
    input().removeAttribute("accept");
    await user.upload(input(), new File(["# Titre"], "README.md", { type: "" }));
    await waitFor(() => expect(sent.upload).toHaveBeenCalled());
    expect(sent.upload.mock.calls[0][1]).toBe("text/markdown");
  });

  it("refuses before it travels — a sixth file — and says why", async () => {
    const user = userEvent.setup();
    sent.upload.mockImplementation((file: File) => Promise.resolve(kept(file.name, file.name)));
    mount();
    const six = Array.from({ length: 6 }, (_, i) => new File(["x"], `f${i}.txt`, { type: "text/plain" }));
    await user.upload(input(), six);

    await waitFor(() => expect(chips()).toHaveLength(6));
    const last = chips()[5];
    expect(last).toHaveAttribute("data-status", "refused");
    expect(within(last).getByTestId("attachment-error")).toHaveTextContent(fr.composer.files.errors.too_many);
    expect(sent.upload).toHaveBeenCalledTimes(5);
  });

  it("a network failure is said and tried again — the words and the other files untouched", async () => {
    const user = userEvent.setup();
    sent.upload
      .mockResolvedValueOnce(kept("a1", "first.txt"))
      .mockRejectedValueOnce(new ApiError(0, "/intentions/attachments", "Cannot reach the API"))
      .mockResolvedValueOnce(kept("a2", "second.txt"));
    mount();
    await user.type(screen.getByTestId("intention-input"), "Pourquoi payment-api est lente ?");
    await user.upload(input(), new File(["one"], "first.txt", { type: "text/plain" }));
    await waitFor(() => expect(chips()[0]).toHaveAttribute("data-status", "kept"));
    await user.upload(input(), new File(["two"], "second.txt", { type: "text/plain" }));

    await waitFor(() => expect(chips()[1]).toHaveAttribute("data-status", "failed"));
    expect(within(chips()[1]).getByTestId("attachment-error")).toHaveTextContent(fr.composer.files.errors.network);
    await user.click(within(chips()[1]).getByTestId("attachment-retry"));

    await waitFor(() => expect(chips()[1]).toHaveAttribute("data-status", "kept"));
    expect(chips()[0]).toHaveAttribute("data-status", "kept");
    expect(screen.getByTestId("intention-input")).toHaveValue("Pourquoi payment-api est lente ?");
  });

  it("a refusal by the server is said, never retried", async () => {
    const user = userEvent.setup();
    sent.upload.mockRejectedValue(
      new ApiError(415, "/intentions/attachments", "refused", "validation_failed", {
        file: "file_content_mismatch",
      }),
    );
    mount();
    await user.upload(input(), new File(["hello"], "fake.pdf", { type: "application/pdf" }));

    await waitFor(() => expect(chips()[0]).toHaveAttribute("data-status", "failed"));
    expect(within(chips()[0]).getByTestId("attachment-error")).toHaveTextContent(
      fr.composer.files.errors.file_content_mismatch,
    );
    expect(within(chips()[0]).queryByTestId("attachment-retry")).toBeNull();
  });

  it("removed before asking: removed on the server once kept, let go on its way", async () => {
    const user = userEvent.setup();
    const upload = held();
    sent.upload.mockResolvedValueOnce(kept("a1", "kept.txt")).mockReturnValueOnce(upload.promise);
    mount();
    await user.upload(input(), new File(["one"], "kept.txt", { type: "text/plain" }));
    await waitFor(() => expect(chips()[0]).toHaveAttribute("data-status", "kept"));
    await user.click(screen.getByRole("button", { name: "Retirer kept.txt" }));
    expect(chips()).toHaveLength(0);
    expect(sent.remove).toHaveBeenCalledWith("a1");

    await user.upload(input(), new File(["two"], "going.txt", { type: "text/plain" }));
    const signal = sent.upload.mock.calls[1][2] as AbortSignal;
    await user.click(screen.getByRole("button", { name: "Retirer going.txt" }));
    expect(signal.aborted).toBe(true);
    expect(chips()).toHaveLength(0);
    // Its late answer changes nothing.
    upload.answer(kept("a2", "going.txt"));
    await Promise.resolve();
    expect(chips()).toHaveLength(0);
    expect(sent.remove).toHaveBeenCalledTimes(1);
  });

  it("nothing is asked while a file is on its way", async () => {
    const user = userEvent.setup();
    const upload = held();
    sent.upload.mockReturnValue(upload.promise);
    mount();
    await user.type(screen.getByTestId("intention-input"), "Pourquoi payment-api est lente ?");
    await user.upload(input(), new File(["x"], "notes.txt", { type: "text/plain" }));

    expect(screen.getByTestId("intention-submit")).toBeDisabled();
    expect(screen.getByText(fr.composer.files.waiting)).toBeInTheDocument();
    upload.answer(kept("a1", "notes.txt"));
    await waitFor(() => expect(screen.getByTestId("intention-submit")).toBeEnabled());
  });
});
