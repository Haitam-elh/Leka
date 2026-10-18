/**
 * The profile, changed from the account menu.
 *
 * What it is for first: an account made before registration asked has no
 * name, and the overview greets it as "halimi.ha13". Here it gets one, and
 * the menu shows it at once — no reload.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LocaleProvider } from "@/lib/i18n/locale-provider";

// One router for the whole test, as Next gives: a new one per render would
// make the shell ask /auth/me again and paint over the saved profile.
vi.mock("next/navigation", () => {
  const router = { push: vi.fn(), replace: vi.fn() };
  return { usePathname: () => "/", useRouter: () => router };
});

const BEFORE = {
  id: "u1",
  email: "halimi.ha13@acme.example",
  email_verified_at: null,
  last_login_at: null,
  first_name: null,
  last_name: null,
  company: null,
  job_title: null,
  company_size: null,
};

const updateProfile = vi.fn();
vi.mock("@/lib/auth", async (original) => ({
  ...(await original<typeof import("@/lib/auth")>()),
  auth: {
    me: vi.fn().mockResolvedValue({
      user: BEFORE,
      workspaces: [{ id: "w1", name: "Acme Corp", slug: "acme", role: "owner" }],
      active_workspace_id: "w1",
    }),
    logout: vi.fn(),
    updateProfile: (...args: unknown[]) => updateProfile(...args),
  },
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

vi.mock("@/lib/nav-badges", () => ({ useNavBadges: () => ({}) }));

const { ShellProvider } = await import("@/components/shell/shell-provider");
const { UserMenu } = await import("@/components/shell/user-menu");

async function openProfile() {
  const user = userEvent.setup();
  render(
    <LocaleProvider>
      <ShellProvider>
        <UserMenu />
      </ShellProvider>
    </LocaleProvider>,
  );
  expect(await screen.findByText("halimi.ha13")).toBeVisible();
  await user.click(screen.getByTestId("user-menu"));
  await user.click(await screen.findByTestId("profile"));
  expect(await screen.findByRole("dialog", { name: "Votre profil" })).toBeVisible();
  return user;
}

describe("the profile dialog", () => {
  beforeEach(() => {
    updateProfile.mockReset();
  });

  it("gives an account from before names one, and the menu shows it at once", async () => {
    updateProfile.mockImplementation(async (changes: Record<string, unknown>) => ({
      ...BEFORE,
      ...changes,
    }));
    const user = await openProfile();

    await user.type(screen.getByLabelText("Prénom"), "Haitam");
    await user.type(screen.getByLabelText("Nom"), "El Halimi");
    await user.type(screen.getByLabelText("Entreprise"), "LEKA");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    // The optional two are sent as null: left empty, they are cleared.
    expect(updateProfile).toHaveBeenCalledWith({
      first_name: "Haitam",
      last_name: "El Halimi",
      company: "LEKA",
      job_title: null,
      company_size: null,
    });
    expect(await screen.findByText("Haitam El Halimi")).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("stays open and says so when the save fails", async () => {
    updateProfile.mockRejectedValue(new Error("down"));
    const user = await openProfile();

    await user.type(screen.getByLabelText("Prénom"), "Haitam");
    await user.type(screen.getByLabelText("Nom"), "El Halimi");
    await user.type(screen.getByLabelText("Entreprise"), "LEKA");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(
      await screen.findByText("Le profil n'a pas pu être enregistré. Réessayez."),
    ).toBeVisible();
    expect(screen.getByRole("dialog", { name: "Votre profil" })).toBeVisible();
  });
});
