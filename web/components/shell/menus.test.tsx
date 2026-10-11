/**
 * The two menus in the shell, driven by the keyboard alone.
 *
 * A menu that only opens under a mouse is a menu half the accessibility
 * criteria of this ticket are about. These press keys: no click anywhere.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock("@/lib/auth", () => ({
  auth: {
    me: vi.fn().mockResolvedValue({
      user: { id: "u1", email: "nora@acme.example", email_verified_at: null, last_login_at: null },
      workspaces: [
        { id: "w1", name: "Acme Corp", slug: "acme", role: "admin" },
        { id: "w2", name: "Globex", slug: "globex", role: "member" },
      ],
      active_workspace_id: "w1",
    }),
    logout: vi.fn().mockResolvedValue(undefined),
  },
  markSignedOut: vi.fn(),
}));

// The shell asks the API what this person may do, as well as who they are.
vi.mock("@/lib/workspace", () => ({
  workspace: {
    current: vi.fn().mockResolvedValue({
      workspace: { id: "w1", name: "Acme Corp", slug: "acme", status: "active" },
      role: "owner",
      permissions: ["workspace:read"],
    }),
  },
}));

const { ShellProvider } = await import("@/components/shell/shell-provider");
const { UserMenu } = await import("@/components/shell/user-menu");
const { WorkspaceSwitcher } = await import("@/components/shell/workspace-switcher");

const fr = DICTIONARIES.fr;

function mount(children: React.ReactNode) {
  return render(
    <LocaleProvider>
      <ShellProvider>{children}</ShellProvider>
    </LocaleProvider>,
  );
}

describe("the account menu", () => {
  it("opens with the keyboard and closes on Escape", async () => {
    const user = userEvent.setup();
    mount(<UserMenu variant="header" />);

    await user.tab();
    expect(screen.getByTestId("user-menu")).toHaveFocus();

    await user.keyboard("{Enter}");
    const signOut = await screen.findByText(fr.shell.signOut);
    expect(signOut).toBeVisible();

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByText(fr.shell.signOut)).not.toBeInTheDocument();
    });
    // Focus comes back where it was, or the next Tab starts from the top of
    // the page and the keyboard user loses their place.
    expect(screen.getByTestId("user-menu")).toHaveFocus();
  });

  it("says the language, and opens the picker of every one LEKA offers", async () => {
    const user = userEvent.setup();
    mount(<UserMenu variant="header" />);

    await user.tab();
    await user.keyboard("{Enter}");

    const item = await screen.findByTestId("language");
    expect(item).toHaveTextContent(fr.shell.language);
    expect(item).toHaveTextContent("Français");

    // Just above the way out.
    await user.keyboard("{End}{ArrowUp}");
    await waitFor(() => expect(item).toHaveFocus());
    await user.keyboard("{Enter}");
    expect(await screen.findByTestId("language-dialog")).toBeVisible();
    expect(screen.getAllByRole("option")).toHaveLength(140);
  });
});

describe("the workspace switcher", () => {
  it("names the current workspace and lists the others", async () => {
    const user = userEvent.setup();
    mount(<WorkspaceSwitcher />);

    // The active one is on the button before anything is opened.
    expect(await screen.findByText("Acme Corp")).toBeVisible();

    await user.tab();
    await user.keyboard("{Enter}");

    expect(await screen.findByTestId("workspace-globex")).toBeVisible();

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByTestId("workspace-globex")).not.toBeInTheDocument();
    });
  });
});
