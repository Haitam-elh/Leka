/**
 * The composer, which is the one box this product is really about.
 *
 * What these protect is the bargain around the Enter key. An intention runs
 * an analysis that costs money and minutes, often takes several lines to
 * write, and must never be sent by a stray keystroke — so Enter writes a
 * newline and ⌘↵ sends. Everything else here guards the same idea: nothing
 * spends the customer's money without a deliberate act.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Form } from "@/components/forms/form";
import { ConfirmProvider } from "@/components/interactions/confirm";
import { useAttachments } from "@/components/intentions/attachments";
import { IntentionComposer } from "@/components/intentions/intention-composer";
import { useLekaForm } from "@/lib/forms/use-leka-form";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { type IntentionDraft, intentionDraftSchema } from "@/lib/validation/intentions";

const fr = DICTIONARIES.fr;

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentWorkspace: () => ({ id: "ws-1", name: "Acme", slug: "acme", role: "owner" }),
}));

// Nothing travels in these: what is refused is refused before it would.
const sent = vi.hoisted(() => ({ upload: vi.fn(), remove: vi.fn() }));
vi.mock("@/lib/intentions/attachments", async (original) => ({
  ...(await original<typeof import("@/lib/intentions/attachments")>()),
  uploadAttachment: sent.upload,
  removeAttachment: sent.remove,
}));

// A voice recorded and written (2026-10-29): the microphone and LEKA's
// transcription, played by the test.
const voice = vi.hoisted(() => ({
  can: false,
  start: vi.fn(),
  transcribe: vi.fn(),
}));
vi.mock("@/lib/recorder", async (original) => ({
  ...(await original<typeof import("@/lib/recorder")>()),
  canRecord: () => voice.can,
  startRecording: voice.start,
}));
vi.mock("@/lib/intentions/api", async (original) => {
  const real = await original<typeof import("@/lib/intentions/api")>();
  return { ...real, intentions: { ...real.intentions, transcribe: voice.transcribe } };
});

const errors = vi.hoisted(() => ({ calls: [] as { title: string }[] }));
vi.mock("@/lib/notify", () => ({
  notify: {
    error: (options: { title: string }) => errors.calls.push(options),
    success: vi.fn(),
    info: vi.fn(),
  },
}));

function mount({ prefilled = "" }: { prefilled?: string } = {}) {
  const onSubmit = vi.fn();

  function Harness() {
    const form = useLekaForm<IntentionDraft>({
      schema: intentionDraftSchema,
      defaultValues: { text: prefilled },
      onSubmit,
    });
    const files = useAttachments();
    return (
      <Form form={form}>
        <IntentionComposer files={files} onSubmit={() => void form.submit()} />
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
  return { onSubmit };
}

const box = () => screen.getByTestId("intention-input");
const send = () => screen.getByTestId("intention-submit");

beforeEach(() => {
  errors.calls = [];
  try {
    window.sessionStorage.clear();
  } catch {
    // No storage in this environment; the composer copes and so does this.
  }
});

describe("the send button", () => {
  it("is refused while the box is empty or only spaces", async () => {
    const user = userEvent.setup();
    mount();

    expect(send()).toBeDisabled();

    await user.type(box(), "    ");
    expect(send()).toBeDisabled();
  });

  it("is refused for a sentence too short to analyse", async () => {
    const user = userEvent.setup();
    mount();

    await user.type(box(), "lent ?");
    expect(send()).toBeDisabled();
  });

  it("says why it is refused, and how much is missing", async () => {
    // A disabled button that does not say why reads as broken.
    const user = userEvent.setup();
    mount();

    await user.type(box(), "lent ?");

    const why = document.getElementById(send().getAttribute("aria-describedby") ?? "");
    expect(why).toHaveTextContent("Encore 4 caractères pour pouvoir lancer");

    await user.type(box(), " vraiment");
    expect(send()).toBeEnabled();
    expect(send()).not.toHaveAttribute("aria-describedby");
  });

  it("opens once there is a real question", async () => {
    const user = userEvent.setup();
    mount();

    await user.type(box(), "Pourquoi l'API est-elle lente ?");
    await waitFor(() => expect(send()).toBeEnabled());
  });
});

describe("the keyboard bargain", () => {
  it("writes a newline on Enter and sends nothing", async () => {
    const user = userEvent.setup();
    const { onSubmit } = mount();

    await user.type(box(), "Pourquoi l'API est-elle lente ?");
    await user.keyboard("{Enter}");
    await user.type(box(), "Depuis hier.");

    expect(onSubmit).not.toHaveBeenCalled();
    expect(box()).toHaveValue("Pourquoi l'API est-elle lente ?\nDepuis hier.");
  });

  it("sends on Control+Enter", async () => {
    const user = userEvent.setup();
    const { onSubmit } = mount();

    await user.type(box(), "Pourquoi l'API est-elle lente ?");
    await user.keyboard("{Control>}{Enter}{/Control}");

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  });

  it("says out loud which shortcut sends", () => {
    mount();

    expect(screen.getByText(fr.composer.submitHint)).toBeInTheDocument();
    expect(box()).toHaveAttribute("aria-keyshortcuts", "Meta+Enter Control+Enter");
  });
});

describe("suggestions", () => {
  it("fill the box in and never send", async () => {
    const user = userEvent.setup();
    const { onSubmit } = mount();

    await user.click(screen.getByRole("button", { name: fr.composer.suggestIncident }));

    await waitFor(() =>
      expect((box() as HTMLTextAreaElement).value).toContain("plus lent depuis hier"),
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("ask before replacing something already written", async () => {
    const user = userEvent.setup();
    mount();

    await user.type(box(), "Ma propre question, écrite à la main.");
    await user.click(screen.getByRole("button", { name: fr.composer.suggestIncident }));

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(fr.composer.replaceTitle);

    await user.click(screen.getByRole("button", { name: fr.interactions.cancel }));

    await waitFor(() => expect(box()).toHaveValue("Ma propre question, écrite à la main."));
  });
});

describe("prefilling and the counter", () => {
  it("starts from the text the palette handed over", () => {
    mount({ prefilled: "Pourquoi le paiement est-il lent ?" });

    expect(box()).toHaveValue("Pourquoi le paiement est-il lent ?");
  });

  it("counts what has been written against the limit", async () => {
    const user = userEvent.setup();
    mount();

    expect(screen.getByText("0 / 2000")).toBeInTheDocument();
    await user.type(box(), "abcde");
    await waitFor(() => expect(screen.getByText("5 / 2000")).toBeInTheDocument());
  });
});

describe("attachments", () => {
  it("refuses a file past the size limit, says which and why — and sends nothing", async () => {
    const user = userEvent.setup();
    mount();

    const tooBig = new File(["x".repeat(11 * 1024 * 1024)], "trace.json", {
      type: "application/json",
    });
    await user.upload(screen.getByTestId("attachment-input") as HTMLInputElement, tooBig);

    const [chip] = await screen.findAllByTestId("attachment");
    expect(chip).toHaveAttribute("data-status", "refused");
    expect(chip).toHaveTextContent("trace.json");
    expect(within(chip).getByTestId("attachment-error")).toHaveTextContent(fr.composer.files.errors.file_too_large);
    expect(sent.upload).not.toHaveBeenCalled();
  });

  it("refuses a type nobody asked for, even dropped", async () => {
    mount();

    // Dropped rather than chosen: the file input already filters on its
    // `accept` attribute, so the only way to hand the composer a refused
    // type is the one path that bypasses it — which is exactly why the
    // check in the code cannot be left to the attribute.
    const wrong = new File(["MZ"], "outil.exe", { type: "application/x-msdownload" });
    fireEvent.drop(screen.getByTestId("composer-dropzone"), {
      dataTransfer: { files: [wrong] },
    });

    const [chip] = await screen.findAllByTestId("attachment");
    expect(chip).toHaveTextContent("outil.exe");
    expect(within(chip).getByTestId("attachment-error")).toHaveTextContent(
      fr.composer.files.errors.file_type_refused,
    );
    expect(sent.upload).not.toHaveBeenCalled();
  });
});

describe("dictation (2026-10-29: « Bientôt », then nothing written, no more)", () => {
  beforeEach(() => {
    voice.can = true;
    voice.start.mockReset();
    voice.transcribe.mockReset();
  });

  it("records, then writes what was said after what was typed", async () => {
    const user = userEvent.setup();
    const recorded = new Blob(["RIFF"], { type: "audio/wav" });
    const stop = vi.fn(async () => recorded);
    voice.start.mockResolvedValue({ stop, cancel: vi.fn() });
    voice.transcribe.mockResolvedValue({ text: "pourquoi le paiement est lent depuis hier" });
    mount({ prefilled: "Bonjour." });

    const dictate = await screen.findByTestId("intention-dictate");
    expect(dictate).toHaveTextContent(fr.composer.dictate);
    expect(dictate).not.toHaveTextContent("Bientôt");
    await user.click(dictate);
    expect(voice.start).toHaveBeenCalled();
    expect(dictate).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("dictation-status")).toHaveTextContent("LEKA vous écoute (0:00)");

    await user.click(dictate);
    await waitFor(() =>
      expect(box()).toHaveValue("Bonjour. pourquoi le paiement est lent depuis hier"),
    );
    expect(stop).toHaveBeenCalled();
    expect(voice.transcribe).toHaveBeenCalledWith(recorded, expect.stringMatching(/^fr/));
    expect(dictate).toHaveAttribute("aria-pressed", "false");
  });

  it("says why it stopped short: the microphone refused, nothing heard, LEKA unable", async () => {
    const user = userEvent.setup();
    const { RecordingRefused } = await import("@/lib/recorder");
    voice.start.mockRejectedValueOnce(new RecordingRefused("denied"));
    mount();
    const dictate = await screen.findByTestId("intention-dictate");
    await user.click(dictate);
    expect(await screen.findByTestId("dictation-status")).toHaveTextContent(
      fr.composer.dictation.problems.denied,
    );

    voice.start.mockResolvedValue({ stop: vi.fn(async () => new Blob(["x"])), cancel: vi.fn() });
    voice.transcribe.mockResolvedValueOnce({ text: "  " });
    await user.click(dictate);
    await user.click(dictate);
    await waitFor(() =>
      expect(screen.getByTestId("dictation-status")).toHaveTextContent(
        fr.composer.dictation.problems.no_speech,
      ),
    );

    const { ApiError } = await import("@/lib/api");
    voice.transcribe.mockRejectedValueOnce(new ApiError(503, "/intentions/transcriptions", "down"));
    await user.click(dictate);
    await user.click(dictate);
    await waitFor(() =>
      expect(screen.getByTestId("dictation-status")).toHaveTextContent(
        fr.composer.dictation.problems.unavailable,
      ),
    );
  });

  it("is not offered where the browser cannot record", () => {
    voice.can = false;
    mount();
    expect(screen.queryByTestId("intention-dictate")).not.toBeInTheDocument();
  });
});
