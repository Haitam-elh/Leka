/**
 * What someone signed in sees with no workspace open.
 *
 * The case behind it: a new account registered from leka-core.com, signed
 * in, and found an empty shell — every page refused, no connectors. It is
 * now asked to create its workspace, named after its company, and sent to
 * Sources.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";

// One router for the whole test, as Next gives.
const push = vi.fn();
vi.mock("next/navigation", () => {
  const router = { push: (...args: unknown[]) => push(...args), replace: vi.fn() };
  return { useRouter: () => router, usePathname: () => "/overview" };
});

let state: unknown;
const retry = vi.fn();
vi.mock("@/components/shell/shell-provider", () => ({
  useShell: () => state,
  useShellRetry: () => retry,
}));

const create = vi.fn();
const enter = vi.fn();
vi.mock("@/lib/workspace", () => ({
  workspace: {
    create: (...args: unknown[]) => create(...args),
    enter: (...args: unknown[]) => enter(...args),
  },
}));

const { WorkspaceGate } = await import("@/components/shell/workspace-gate");

function signedIn(
  workspaces: { id: string; name: string; slug: string; role: string }[],
  open: string | null = null,
) {
  return {
    status: "ready",
    me: {
      user: { id: "u1", email: "karim@acme.example", company: "Acme" },
      workspaces,
      active_workspace_id: open,
    },
    workspace: workspaces.find((w) => w.id === open) ?? null,
    permissions: open ? ["workspace:read"] : [],
  };
}

function mount() {
  return render(
    <LocaleProvider>
      <WorkspaceGate>
        <p>the page</p>
      </WorkspaceGate>
    </LocaleProvider>,
  );
}

describe("the workspace gate", () => {
  beforeEach(() => {
    push.mockReset();
    retry.mockReset();
    create.mockReset().mockResolvedValue({ id: "w-new", name: "Acme" });
    enter.mockReset().mockResolvedValue({});
  });

  it("lets a workspace member straight through", () => {
    const acme = { id: "w1", name: "Acme", slug: "acme", role: "owner" };
    state = signedIn([acme], "w1");

    mount();

    expect(screen.getByText("the page")).toBeVisible();
  });

  it("asks a new account to create its workspace, named after its company", async () => {
    state = signedIn([]);
    const user = userEvent.setup();

    mount();

    expect(screen.queryByText("the page")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Nom de l'espace")).toHaveValue("Acme");
    await user.click(screen.getByRole("button", { name: "Créer l'espace" }));

    expect(create).toHaveBeenCalledWith("Acme");
    expect(enter).toHaveBeenCalledWith("w-new");
    expect(push).toHaveBeenCalledWith("/sources");
    expect(retry).toHaveBeenCalled();
  });

  it("says so, and stays, when the workspace cannot be created", async () => {
    state = signedIn([]);
    create.mockRejectedValue(new Error("down"));
    const user = userEvent.setup();

    mount();
    await user.click(screen.getByRole("button", { name: "Créer l'espace" }));

    expect(await screen.findByText("L'espace n'a pas pu être créé. Réessayez.")).toBeVisible();
    expect(push).not.toHaveBeenCalled();
  });

  it("offers the workspaces someone already has when none is open", async () => {
    state = signedIn([{ id: "w1", name: "LEKA", slug: "leka", role: "member" }]);
    const user = userEvent.setup();

    mount();
    await user.click(screen.getByRole("button", { name: "Ouvrir" }));

    expect(enter).toHaveBeenCalledWith("w1");
    expect(push).toHaveBeenCalledWith("/overview");
    expect(create).not.toHaveBeenCalled();
  });
});
