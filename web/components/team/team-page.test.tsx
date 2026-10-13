/**
 * Équipe & accès (mockup 15).
 *
 * What these protect: who is in the workspace is the API's — names,
 * addresses, roles, last sign-in — with the figures above it and the split
 * by role; an admin invites (the link also shown), changes a role, removes
 * someone only once asked, revokes an invitation; the last owner refused is
 * said in words; a member reads it all and changes nothing; the security
 * settings say what LEKA does.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";
import type { PendingInvitation, TeamMember } from "@/lib/team";

const ME = "u-1";
const permissions = vi.hoisted(() => ({
  value: ["workspace:read", "member:invite", "member:update_role", "member:remove"],
}));
const api = vi.hoisted(() => ({
  members: vi.fn(),
  invitations: vi.fn(),
  invite: vi.fn(),
  changeRole: vi.fn(),
  remove: vi.fn(),
  revoke: vi.fn(),
  accept: vi.fn(),
}));
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));

vi.mock("next/navigation", () => ({ usePathname: () => "/team" }));
vi.mock("@/lib/team", async (original) => ({
  ...(await original<typeof import("@/lib/team")>()),
  team: api,
}));
vi.mock("@/lib/environment", async (original) => ({
  ...(await original<typeof import("@/lib/environment")>()),
  environment: {
    get: async () => ({ nodes: [{ type: "team" }, { type: "team" }, { type: "service" }] }),
  },
}));
vi.mock("@/lib/notify", () => ({ notify: notices }));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
  useCurrentUser: () => ({ id: ME }),
}));

const { TeamScreen } = await import("@/components/team/team-page");
const { ApiError } = await import("@/lib/api");

function member(overrides: Partial<TeamMember> = {}): TeamMember {
  return {
    id: "m-1",
    user_id: ME,
    role: "owner",
    joined_at: "2026-10-01T10:00:00Z",
    email: "haitam@leka.example",
    first_name: "Haitam",
    last_name: "El Halimi",
    last_login_at: "2026-10-08T09:00:00Z",
    ...overrides,
  };
}
const NORA = member({
  id: "m-2",
  user_id: "u-2",
  role: "member",
  email: "nora@leka.example",
  first_name: "Nora",
  last_name: null,
  last_login_at: null,
});
const PENDING: PendingInvitation = {
  id: "i-1",
  email: "karim@leka.example",
  role: "admin",
  created_at: "2026-10-08T09:00:00Z",
  expires_at: "2026-10-15T09:00:00Z",
  expired: false,
  invited_by: "Haitam El Halimi",
};

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <TeamScreen />
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions.value = ["workspace:read", "member:invite", "member:update_role", "member:remove"];
  api.members.mockResolvedValue([member(), NORA]);
  api.invitations.mockResolvedValue([PENDING]);
  api.invite.mockResolvedValue({ invitation: PENDING, token: "tok en" });
  api.changeRole.mockResolvedValue({});
  api.remove.mockResolvedValue(undefined);
  api.revoke.mockResolvedValue(undefined);
});

describe("the team", () => {
  it("lists who is in, its figures and its split, what LEKA's security does", async () => {
    show();
    const rows = await screen.findAllByTestId("team-member");
    expect(rows[0]).toHaveTextContent("Haitam El Halimi (vous)");
    expect(rows[0]).toHaveTextContent("haitam@leka.example");
    expect(rows[1]).toHaveTextContent("Nora");
    expect(rows[1]).toHaveTextContent("Jamais");
    // How many people: the tab says it, no figure repeats it (LEKA-438).
    expect(screen.getByTestId("team-tab-members")).toHaveTextContent("Utilisateurs 2");
    expect(screen.queryByTestId("team-stat-members")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("team-stat-teams")).toHaveTextContent("2"));
    expect(screen.getByTestId("team-stat-invitations")).toHaveTextContent("1");
    // Two people: no split to read yet (LEKA-438).
    expect(screen.queryByTestId("team-split")).not.toBeInTheDocument();
    expect(screen.getByTestId("team-security")).toHaveTextContent(
      "Mot de passe : 12 caractères minimum",
    );
    // One's own seat is not changed from here.
    expect(within(rows[0]).queryByTestId("team-role")).not.toBeInTheDocument();
  });

  it("leaves out a 0 that calls for nothing, and splits by role from four people", async () => {
    api.members.mockResolvedValue([
      member(),
      NORA,
      { ...NORA, id: "m3", user_id: "u3", email: "a@leka.example" },
      { ...NORA, id: "m4", user_id: "u4", email: "b@leka.example" },
    ]);
    api.invitations.mockResolvedValue([]);
    show();
    await screen.findAllByTestId("team-member");
    expect(await screen.findByTestId("team-split")).toHaveTextContent("Propriétaire1");
    expect(screen.getByTestId("team-tab-members")).toHaveTextContent("Utilisateurs 4");
    // Loading, it says "…"; read, its 0 goes.
    await waitFor(() => expect(screen.queryByTestId("team-stat-invitations")).not.toBeInTheDocument());
    expect(screen.queryByTestId("team-stat-roles")).not.toBeInTheDocument();
  });

  it("lets an admin invite, the link also shown", async () => {
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByTestId("team-invite-open"));
    await user.type(screen.getByTestId("invite-email"), "karim@leka.example");
    await user.selectOptions(screen.getByTestId("invite-role"), "admin");
    await user.click(screen.getByTestId("invite-send"));
    await waitFor(() => expect(api.invite).toHaveBeenCalledWith("karim@leka.example", "admin"));
    expect(notices.success).toHaveBeenCalledWith({
      title: "Invitation envoyée à karim@leka.example.",
    });
    expect(await screen.findByTestId("invite-link")).toHaveTextContent("/invitations/tok%20en");
  });

  it("changes a role, removes only once asked, says the last owner", async () => {
    const user = userEvent.setup();
    show();
    const [, nora] = await screen.findAllByTestId("team-member");
    await user.selectOptions(within(nora).getByTestId("team-role"), "admin");
    await waitFor(() => expect(api.changeRole).toHaveBeenCalledWith("m-2", "admin"));

    await user.click(within(nora).getByTestId("team-remove"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("nora@leka.example");
    await user.click(within(dialog).getByRole("button", { name: "Retirer" }));
    await waitFor(() => expect(api.remove).toHaveBeenCalledWith("m-2"));

    api.changeRole.mockRejectedValue(new ApiError(409, "/members/m-2", "Last owner.", "conflict"));
    await user.selectOptions(within(nora).getByTestId("team-role"), "member");
    await waitFor(() =>
      expect(notices.error).toHaveBeenCalledWith({
        title: "C'est le dernier propriétaire : nommez-en un autre d'abord.",
      }),
    );
  });

  it("revokes an invitation", async () => {
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByTestId("team-tab-invitations"));
    const [invitation] = await screen.findAllByTestId("team-invitation");
    expect(invitation).toHaveTextContent("karim@leka.example");
    expect(invitation).toHaveTextContent("Administrateur · par Haitam El Halimi");
    await user.click(within(invitation).getByTestId("team-revoke"));
    await waitFor(() => expect(api.revoke).toHaveBeenCalledWith("i-1"));
  });

  it("lets a member read it and change nothing", async () => {
    permissions.value = ["workspace:read"];
    show();
    await screen.findAllByTestId("team-member");
    expect(screen.queryByTestId("team-invite-open")).not.toBeInTheDocument();
    expect(screen.queryByTestId("team-role")).not.toBeInTheDocument();
    expect(screen.queryByTestId("team-tab-invitations")).not.toBeInTheDocument();
    expect(api.invitations).not.toHaveBeenCalled();
    expect(
      screen.getByText("Seuls les admins invitent, changent un rôle ou retirent quelqu'un."),
    ).toBeInTheDocument();
  });
});
