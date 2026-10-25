/**
 * « Installer dans votre environnement » (2026-10-25).
 *
 * What these protect: offered for an agent that has a package only; three
 * ways — a terminal, an MCP client, a model without tools —, each with the
 * authenticated download and its commands to copy — Windows', macOS' or
 * Linux's, as chosen; nothing through LEKA, said.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { InstallAgent } from "@/components/capabilities/install-dialog";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

function show(agentKey: string) {
  return render(
    <LocaleProvider>
      <InstallAgent agentKey={agentKey} />
    </LocaleProvider>,
  );
}

describe("« Installer dans votre environnement »", () => {
  it("three ways, each its download and its commands to copy", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    show("application-architecture");
    await user.click(screen.getByTestId("install-open"));
    const dialog = await screen.findByTestId("install-dialog");
    expect(dialog).toHaveTextContent("rien ne passe par LEKA");
    expect(within(dialog).getByTestId("install-download")).toHaveAttribute(
      "href",
      expect.stringContaining("/api/v1/capabilities/application-architecture/package"),
    );
    // macOS: its own folder's environment, the deck of a journey.
    await user.click(screen.getByTestId("install-system-macos"));
    expect(screen.getByTestId("install-system-macos")).toHaveAttribute("aria-checked", "true");
    // Every step written: the folder, the zip just downloaded unzipped in it,
    // the install, the .env to fill, then read and run — nothing to guess.
    const [install, env, check, run] = within(dialog).getAllByRole("code").map((c) => c.textContent ?? "");
    expect(install).toContain("mkdir -p ~/architecte && cd ~/architecte");
    expect(install).toContain('unzip -o "$(ls -t ~/Downloads/leka-architect*.zip | head -1)"');
    expect(install).toContain(".venv/bin/pip install ./leka-architect");
    expect(install).not.toContain("spaces"); // never before .env is filled
    expect(env).toContain("CONFLUENCE_TOKEN=<votre token : https://id.atlassian.com/manage-profile/security/api-tokens>");
    expect(check).toBe("cd ~/architecte\n.venv/bin/leka-architect spaces");
    expect(run).toContain('.venv/bin/leka-architect deck --space MO --parcours "Paiement CB"');
    // Pasted into macOS' zsh, a « # » is a command and a trailing one is
    // arguments: no comment in what is pasted into a terminal.
    for (const block of [install, check, run]) {
      expect(block.split("\n").filter((line) => /(^|\s)#/.test(line))).toEqual([]);
    }
    expect(screen.getByTestId("install-python")).toHaveTextContent("brew install python@3.12");
    await user.click(within(dialog).getAllByTestId("install-copy")[0]);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining(".venv/bin/pip install ./leka-architect")));
    expect(within(dialog).getAllByTestId("install-copy")[0]).toHaveTextContent("Copié");
    // Windows: PowerShell's.
    await user.click(screen.getByTestId("install-system-windows"));
    expect(dialog).toHaveTextContent("py -3 -m venv .venv");
    expect(dialog).toHaveTextContent("Expand-Archive $zip -DestinationPath . -Force");
    expect(dialog).toHaveTextContent("explorer rapport");
    expect(dialog).toHaveTextContent(".venv\\Scripts\\python -m pip install .\\leka-architect");
    expect(dialog).toHaveTextContent("Copy-Item leka-architect\\.env.example .env");

    await user.click(screen.getByTestId("install-tab-mcp"));
    expect(dialog).toHaveTextContent('"command": "${workspaceFolder}\\\\.venv\\\\Scripts\\\\leka-architect.exe"');
    expect(dialog).toHaveTextContent("/architecte-applicatif");
    await user.click(screen.getByTestId("install-system-linux"));
    expect(dialog).toHaveTextContent('"command": "${workspaceFolder}/.venv/bin/leka-architect"');
    expect(dialog).toHaveTextContent(
      "claude mcp add leka-architect --env ARCHITECT_ENV=$HOME/architecte/.env -- $HOME/architecte/.venv/bin/leka-architect mcp",
    );
    await user.click(screen.getByTestId("install-tab-other"));
    expect(dialog).toHaveTextContent("ARCHITECT_LLM_PROVIDER=azure");
    expect(dialog).toHaveTextContent("leka-architect prompts --output ./prompts");
    expect(dialog).toHaveTextContent("leka-architect render-deck --deck deck.json");
    expect(dialog).toHaveTextContent("Le paquet ne contient aucun secret");
  });

  it("not offered for an agent without a package", () => {
    const { container } = show("code-review");
    expect(container).toBeEmptyDOMElement();
  });
});
