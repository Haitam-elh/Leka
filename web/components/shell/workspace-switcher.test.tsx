/**
 * The sidebar's workspace switcher: choosing another workspace tells the
 * API, then reloads on its overview; the open one does nothing; a refusal
 * is said.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";

const ACME = { id: "w-1", name: "Acme", slug: "acme" };
const GLOBEX = { id: "w-2", name: "Globex", slug: "globex" };
vi.mock("@/components/shell/shell-provider", () => ({
  useCurrentWorkspace: () => ACME,
  useWorkspaces: () => [ACME, GLOBEX],
}));

const enter = vi.fn();
vi.mock("@/lib/workspace", () => ({
  workspace: { enter: (...args: unknown[]) => enter(...args) },
}));
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));
vi.mock("@/lib/notify", () => ({ notify: notices }));

const { WorkspaceSwitcher } = await import("@/components/shell/workspace-switcher");

const assign = vi.fn();

async function choose(slug: string) {
  const user = userEvent.setup();
  render(
    <LocaleProvider>
      <WorkspaceSwitcher />
    </LocaleProvider>,
  );
  await user.click(screen.getByRole("button", { name: "Changer de workspace" }));
  await user.click(await screen.findByTestId(`workspace-${slug}`));
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("location", { ...window.location, assign });
});

describe("the workspace switcher", () => {
  it("enters another workspace and reloads on its overview", async () => {
    enter.mockResolvedValue(undefined);
    await choose("globex");
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/overview"));
    expect(enter).toHaveBeenCalledWith("w-2");
  });

  it("does nothing for the open one", async () => {
    await choose("acme");
    expect(enter).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });

  it("says when the switch is refused", async () => {
    enter.mockRejectedValue(new Error("403"));
    await choose("globex");
    await waitFor(() =>
      expect(notices.error).toHaveBeenCalledWith({ title: "Impossible d'ouvrir ce workspace. Réessayez." }),
    );
    expect(assign).not.toHaveBeenCalled();
  });
});
