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
}));

const { ShellProvider } = await import("@/components/shell/shell-provider");
const { UserMenu } = await import("@/components/shell/user-menu");
const { WorkspaceSwitcher } = await import("@/components/shell/workspace-switcher");

const en = DICTIONARIES.en;

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
    const signOut = await screen.findByText(en.shell.signOut);
    expect(signOut).toBeVisible();

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByText(en.shell.signOut)).not.toBeInTheDocument();
    });
    // Focus comes back where it was, or the next Tab starts from the top of
    // the page and the keyboard user loses their place.
    expect(screen.getByTestId("user-menu")).toHaveFocus();
  });

  it("offers the languages the interface speaks", async () => {
    const user = userEvent.setup();
    mount(<UserMenu variant="header" />);

    await user.tab();
    await user.keyboard("{Enter}");

    expect(await screen.findByText(en.languages.fr)).toBeVisible();
    expect(screen.getByText(en.languages.en)).toBeVisible();
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
