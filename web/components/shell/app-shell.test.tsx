/**
 * The shell before it can draw itself: loading, failing, and trying again.
 *
 * It used to print the error's own message where the page should be —
 * "Cannot reach the API at http://localhost:8000. Is it running?" — to
 * people who run nothing, with no way forward but the reload button.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

// One router for the whole test, as Next gives: the session check depends
// on it, and a new object on every render would re-run the check after each
// one and hide the very failure this file is about.
const router = { push: vi.fn(), replace: vi.fn(), back: vi.fn() };
vi.mock("next/navigation", () => ({
  usePathname: () => "/overview",
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => router,
}));

const me = vi.fn();
vi.mock("@/lib/auth", () => ({ auth: { me: () => me(), logout: vi.fn() } }));
vi.mock("@/lib/workspace", () => ({
  workspace: {
    current: vi.fn().mockResolvedValue({
      workspace: { id: "w1", name: "Acme Corp", slug: "acme", status: "active" },
      role: "owner",
      permissions: [],
    }),
  },
}));

const { ShellProvider } = await import("@/components/shell/shell-provider");
const { AppShell } = await import("@/components/shell/app-shell");

const fr = DICTIONARIES.fr;

describe("the shell, when the session cannot be checked", () => {
  it("says so in words a person can act on, and tries again when asked", async () => {
    me.mockRejectedValueOnce(
      new ApiError(0, "/auth/me", "Cannot reach the API at http://localhost:8000. Is it running?"),
    ).mockResolvedValueOnce({
      user: { id: "u1", email: "nora@acme.example", email_verified_at: null, last_login_at: null },
      workspaces: [{ id: "w1", name: "Acme Corp", slug: "acme", role: "owner" }],
      active_workspace_id: "w1",
    });
    const user = userEvent.setup();

    render(
      <LocaleProvider>
        <ShellProvider>
          <AppShell>
            <p>the page</p>
          </AppShell>
        </ShellProvider>
      </LocaleProvider>,
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(fr.states.unreachableTitle);
    expect(screen.queryByText(/localhost/)).not.toBeInTheDocument();
    expect(screen.queryByText("the page")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: fr.states.retry }));

    expect(await screen.findByText("the page")).toBeInTheDocument();
    expect(me).toHaveBeenCalledTimes(2);
  });
});
