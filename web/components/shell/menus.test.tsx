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

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => router,
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

// The decisions waiting: none, here.
vi.mock("@/lib/nav-badges", () => ({ useNavBadges: () => ({}) }));

const allowed = vi.hoisted(() => ({ value: ["workspace:read"] }));

// The shell asks the API what this person may do, as well as who they are.
vi.mock("@/lib/workspace", () => ({
  workspace: {
    current: vi.fn().mockImplementation(async () => ({
      workspace: { id: "w1", name: "Acme Corp", slug: "acme", status: "active" },
      role: "owner",
      permissions: allowed.value,
    })),
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
    mount(<UserMenu />);

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

  it("opens the settings", async () => {
    // It went nowhere: an item with nothing to do (2026-10-14).
    const user = userEvent.setup();
    mount(<UserMenu />);
    await user.click(await screen.findByTestId("user-menu"));
    await user.click(await screen.findByTestId("settings"));
    expect(router.push).toHaveBeenLastCalledWith("/settings");
  });

  it("holds the pages of running the workspace, each to who may open it (LEKA-494)", async () => {
    allowed.value = ["workspace:read", "source:read", "access:read", "member:invite", "workspace:update"];
    const user = userEvent.setup();
    const { unmount } = mount(<UserMenu />);
    await user.click(await screen.findByTestId("user-menu"));
    for (const id of ["sources", "governance", "team", "billing"] as const) {
      expect(await screen.findByTestId(`menu-${id}`)).toHaveTextContent(fr.nav[id]);
    }
    await user.click(screen.getByTestId("menu-billing"));
    expect(router.push).toHaveBeenLastCalledWith("/billing");
    unmount();

    // A member: none of them.
    allowed.value = ["workspace:read"];
    mount(<UserMenu />);
    await user.click(await screen.findByTestId("user-menu"));
    await screen.findByTestId("settings");
    expect(screen.queryByTestId("menu-sources")).toBeNull();
    expect(screen.queryByTestId("menu-billing")).toBeNull();
    // The main pages, for a phone: what a member may open.
    expect(screen.getByTestId("menu-home")).toHaveTextContent("Accueil");
    expect(screen.queryByTestId("menu-history")).toBeNull();
    allowed.value = ["workspace:read"];
  });

  it("says the language, and opens the picker of every one LEKA offers", async () => {
    const user = userEvent.setup();
    mount(<UserMenu />);

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
