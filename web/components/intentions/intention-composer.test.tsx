/**
 * The composer, which is the one box this product is really about.
 *
 * What these protect is the bargain around the Enter key. An intention runs
 * an analysis that costs money and minutes, often takes several lines to
 * write, and must never be sent by a stray keystroke — so Enter writes a
 * newline and ⌘↵ sends. Everything else here guards the same idea: nothing
 * spends the customer's money without a deliberate act.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Form } from "@/components/forms/form";
import { ConfirmProvider } from "@/components/interactions/confirm";
import { type Attachment, IntentionComposer } from "@/components/intentions/intention-composer";
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
  let attachments: Attachment[] = [];

  function Harness() {
    const form = useLekaForm<IntentionDraft>({
      schema: intentionDraftSchema,
      defaultValues: { text: prefilled },
      onSubmit,
    });
    return (
      <Form form={form}>
        <IntentionComposer
          attachments={attachments}
          onAttachmentsChange={(next) => {
            attachments = next;
          }}
          onSubmit={() => void form.submit()}
        />
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
    expect(why).toHaveTextContent("Encore 4 caractère(s) pour pouvoir lancer");

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
  it("refuses a file past the size limit, and says which", async () => {
    const user = userEvent.setup();
    mount();

    const tooBig = new File(["x".repeat(11 * 1024 * 1024)], "trace.json", {
      type: "application/json",
    });
    const input = document.querySelector('input[type="file"]');
    await user.upload(input as HTMLInputElement, tooBig);

    await waitFor(() => expect(errors.calls).toHaveLength(1));
    expect(errors.calls[0].title).toContain("trace.json");
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

    await waitFor(() => expect(errors.calls).toHaveLength(1));
    expect(errors.calls[0].title).toContain("outil.exe");
  });
});
