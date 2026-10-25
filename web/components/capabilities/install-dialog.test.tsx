/**
 * « Installer dans votre environnement » (2026-10-25: « personne va le
 * faire »).
 *
 * What these protect: offered for an agent that has a package only; three
 * steps — its details, two downloads, one command —; a model chosen fills
 * its defaults; the installer is made here, the details typed in it, and
 * nothing is sent anywhere; every « Détail » says where to click, for the
 * system chosen; by hand, the same steps, no comment in what is pasted.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InstallAgent } from "@/components/capabilities/install-dialog";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

function show(agentKey: string) {
  return render(
    <LocaleProvider>
      <InstallAgent agentKey={agentKey} />
    </LocaleProvider>,
  );
}

/** What the browser saves: the blobs made, no file written. */
function saved(): Blob[] {
  const made: Blob[] = [];
  vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
    made.push(blob as Blob);
    return "blob:installateur";
  });
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  return made;
}

afterEach(() => vi.restoreAllMocks());

describe("« Installer dans votre environnement »", () => {
  it("three steps: the details stay here, the installer is made with them", async () => {
    const user = userEvent.setup();
    const fetched = vi.spyOn(globalThis, "fetch");
    const made = saved();
    show("application-architecture");
    await user.click(screen.getByTestId("install-open"));
    const dialog = await screen.findByTestId("install-dialog");
    expect(dialog).toHaveTextContent("rien ne passe par LEKA");
    for (const n of [1, 2, 3]) expect(within(dialog).getByTestId(`install-step-${n}`)).toBeVisible();
    expect(within(dialog).getByTestId("install-stay")).toHaveTextContent("LEKA ne les reçoit pas");
    expect(within(dialog).getByTestId("install-download")).toHaveAttribute(
      "href",
      expect.stringContaining("/api/v1/capabilities/application-architecture/package"),
    );

    await user.click(screen.getByTestId("install-system-macos"));
    await user.type(screen.getByTestId("install-confluence-url"), "https://acme.atlassian.net");
    await user.type(screen.getByTestId("install-confluence-email"), "ada@acme.example");
    await user.type(screen.getByTestId("install-confluence-token"), "jeton-secret");
    expect(screen.getByTestId("install-confluence-token")).toHaveAttribute("type", "password");
    // Where to make the token: its page, a link.
    expect(within(screen.getByTestId("install-token-how")).getByRole("link")).toHaveAttribute(
      "href",
      "https://id.atlassian.com/manage-profile/security/api-tokens",
    );
    // Copilot by default: no key asked.
    expect(screen.queryByTestId("install-model-key")).not.toBeInTheDocument();
    await user.click(screen.getByTestId("install-model-gemini"));
    expect(screen.getByTestId("install-model-name")).toHaveValue("gemini-3.8-flash");
    expect(within(screen.getByTestId("install-key-how")).getByRole("link")).toHaveAttribute(
      "href",
      "https://aistudio.google.com/apikey",
    );
    await user.type(screen.getByTestId("install-model-key"), "cle-secrete");

    await user.click(screen.getByTestId("install-installer"));
    expect(made).toHaveLength(1);
    const script = await made[0].text();
    expect(script.startsWith("#!/usr/bin/env bash")).toBe(true);
    expect(script).toContain("CONFLUENCE_TOKEN=jeton-secret");
    expect(script).toContain("ARCHITECT_LLM_API_KEY=cle-secrete");
    // Never sent: no request at all.
    expect(fetched).not.toHaveBeenCalled();

    // The one command, then how to launch.
    expect(dialog).toHaveTextContent('bash "$(ls -t ~/Downloads/installer-architecte*.sh | head -1)"');
    expect(within(dialog).getByTestId("install-launch")).toHaveTextContent("Lancer l'architecte");
    expect(within(dialog).getByTestId("install-open-how")).toHaveTextContent("Cmd + Espace");
  });

  it("Windows: PowerShell's command, its clicks, its installer; by hand, no comment", async () => {
    const user = userEvent.setup();
    const made = saved();
    show("application-architecture");
    await user.click(screen.getByTestId("install-open"));
    const dialog = await screen.findByTestId("install-dialog");
    await user.click(screen.getByTestId("install-system-windows"));
    expect(dialog).toHaveTextContent("powershell -ExecutionPolicy Bypass -File");
    expect(within(dialog).getByTestId("install-open-how")).toHaveTextContent("touche Windows");
    await user.click(screen.getByTestId("install-installer"));
    const script = await made[0].text();
    expect(script).toContain('$ErrorActionPreference = "Stop"');
    const manual = within(dialog).getByTestId("install-manual");
    const blocks = within(manual)
      .getAllByRole("code")
      .map((code) => code.textContent ?? "");
    expect(blocks[0]).toContain("Expand-Archive $zip -DestinationPath . -Force");
    for (const block of blocks) {
      expect(block.split("\n").filter((line) => /(^|\s)#/.test(line))).toEqual([]);
    }
  });

  it("not offered for an agent without a package", () => {
    const { container } = show("code-review");
    expect(container).toBeEmptyDOMElement();
  });
});
