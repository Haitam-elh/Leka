/**
 * The account menu calls a person by the name they gave when registering,
 * and falls back to their address for an account made before it was asked.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

const me = vi.fn();
vi.mock("@/lib/auth", () => ({
  auth: { me: (...args: unknown[]) => me(...args), logout: vi.fn() },
  markSignedOut: vi.fn(),
}));

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

function answer(profile: Record<string, string | null>) {
  return {
    user: {
      id: "u1",
      email: "nora@acme.example",
      email_verified_at: null,
      last_login_at: null,
      ...profile,
    },
    workspaces: [{ id: "w1", name: "Acme Corp", slug: "acme", role: "owner" }],
    active_workspace_id: "w1",
  };
}

function mount() {
  return render(
    <LocaleProvider>
      <ShellProvider>
        <UserMenu />
      </ShellProvider>
    </LocaleProvider>,
  );
}

describe("the name on the account menu", () => {
  beforeEach(() => me.mockReset());

  it("is the one given at registration, with its initials", async () => {
    me.mockResolvedValue(answer({ first_name: "Nora", last_name: "Diallo" }));

    mount();

    expect(await screen.findByText("Nora Diallo")).toBeVisible();
    expect(screen.getByText("ND")).toBeVisible();
  });

  it("is the address's first part for an account made before names were asked", async () => {
    me.mockResolvedValue(answer({ first_name: null, last_name: null }));

    mount();

    expect(await screen.findByText("nora")).toBeVisible();
    expect(screen.getByText("N")).toBeVisible();
  });
});
