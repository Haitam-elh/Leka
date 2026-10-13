/**
 * Roles and policies of the workspace's own (LEKA-403).
 *
 * What these protect: a role is said with its base, what it adds and takes
 * away, how many hold it; it is created from a name — its key made of it —
 * a base, what it adds among what its base lacks; it is given to a person
 * whose seat has its base, and taken back; a policy is said in words — what
 * it refuses, for whom, from what risk, at what priority — created, turned
 * off; every change is said in the history.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import type { AccessModel, Policy } from "@/lib/access";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const api = vi.hoisted(() => ({
  roles: vi.fn(),
  saveRole: vi.fn(),
  deleteRole: vi.fn(),
  assignments: vi.fn(),
  assign: vi.fn(),
  policies: vi.fn(),
  createPolicy: vi.fn(),
  updatePolicy: vi.fn(),
  deletePolicy: vi.fn(),
  history: vi.fn(),
}));
const people = vi.hoisted(() => ({ members: vi.fn() }));

vi.mock("@/lib/access", async (original) => ({
  ...(await original<typeof import("@/lib/access")>()),
  access: api,
}));
vi.mock("@/lib/team", async (original) => ({
  ...(await original<typeof import("@/lib/team")>()),
  team: people,
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { HistoryCard, PoliciesCard, RolesCard } = await import("@/components/governance/roles-policies");

const MODEL = {
  roles: [
    { role: "member", permissions: ["workspace:read", "source:read", "intention:create"] },
    { role: "admin", permissions: ["workspace:read", "source:read", "intention:create", "intention:approve"] },
    { role: "owner", permissions: ["workspace:read", "workspace:delete"] },
  ],
  permissions: ["workspace:read", "source:read", "intention:create", "intention:approve", "workspace:delete"],
  writes: [],
  mine: ["policy:manage"],
  role: "admin",
  custom_role: null,
} as unknown as AccessModel;

const POLICY: Policy = {
  id: "p1",
  updated_at: "2026-10-10T09:00:00Z",
  name: "Pas d'agent risqué",
  description: null,
  effect: "deny",
  actions: ["agent:run"],
  roles: [],
  resource_types: ["capability"],
  risk_at_least: "medium",
  kinds: [],
  categories: [],
  priority: 50,
  enabled: true,
};

function show(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>{node}</ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.roles.mockResolvedValue([
    {
      key: "tech-lead",
      name: "Tech Lead",
      description: null,
      base: "member",
      added: ["intention:approve"],
      removed: ["source:read"],
      permissions: ["workspace:read", "intention:create", "intention:approve"],
      holders: 0,
    },
  ]);
  api.assignments.mockResolvedValue([]);
  api.policies.mockResolvedValue([POLICY]);
  api.history.mockResolvedValue([
    {
      id: "h1",
      subject_type: "role",
      subject_id: "tech-lead",
      kind: "created",
      by: "u",
      at: "2026-10-10T09:00:00Z",
      before: null,
      after: { name: "Tech Lead" },
    },
  ]);
  api.saveRole.mockResolvedValue({});
  api.assign.mockResolvedValue({});
  api.createPolicy.mockResolvedValue(POLICY);
  api.updatePolicy.mockResolvedValue(POLICY);
  people.members.mockResolvedValue([
    { id: "m1", user_id: "u-nora", role: "member", email: "nora@acme.io", first_name: "Nora", last_name: "Diallo" },
    { id: "m2", user_id: "u-sam", role: "admin", email: "sam@acme.io", first_name: "Sam", last_name: null },
  ]);
});

describe("roles of the workspace's own", () => {
  it("says each with its base and what it adds and takes away, and gives it on its base", async () => {
    const user = userEvent.setup();
    show(<RolesCard model={MODEL} canManage />);
    const role = await screen.findByTestId("custom-roles");
    expect(role).toHaveTextContent("Tech Lead");
    expect(role).toHaveTextContent("sur Membre");
    expect(role).toHaveTextContent("+ Approuver une action · − Voir les sources");
    // Only a member's seat may hold a role built on the member's.
    expect(within(role).queryByRole("button", { name: "Sam" })).not.toBeInTheDocument();
    await user.click(await within(role).findByRole("button", { name: "Nora Diallo" }));
    await waitFor(() => expect(api.assign).toHaveBeenCalledWith("u-nora", "tech-lead"));
  });

  it("creates one from a name, among what its base lacks", async () => {
    const user = userEvent.setup();
    show(<RolesCard model={MODEL} canManage />);
    // Out of the page until asked for (LEKA-438).
    expect(screen.queryByTestId("role-form")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Nouveau rôle" }));
    const form = await screen.findByTestId("role-form");
    expect(screen.getByRole("dialog", { name: "Nouveau rôle" })).toContainElement(form);
    await user.type(within(form).getByLabelText("Nom"), "Sécurité Ops");
    const adds = within(form).getByTestId("role-added");
    expect(adds).not.toHaveTextContent("Supprimer l'espace");
    await user.click(within(adds).getByLabelText("Approuver une action"));
    await user.click(within(form).getByRole("button", { name: "Créer le rôle" }));
    await waitFor(() =>
      expect(api.saveRole).toHaveBeenCalledWith("securite-ops", {
        name: "Sécurité Ops",
        base: "member",
        added: ["intention:approve"],
        removed: [],
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});

describe("policies", () => {
  it("says each in words, and turns one off", async () => {
    const user = userEvent.setup();
    show(<PoliciesCard canManage roles={[]} />);
    const listed = await screen.findByTestId("policies");
    expect(listed).toHaveTextContent("Refuse");
    expect(listed).toHaveTextContent("Pas d'agent risqué");
    expect(listed).toHaveTextContent("Lancer un agent · pour tous · risque moyen ou plus · capability");
    await user.click(within(listed).getByRole("button", { name: "Désactiver" }));
    await waitFor(() =>
      expect(api.updatePolicy).toHaveBeenCalledWith("p1", expect.objectContaining({ enabled: false })),
    );
  });

  it("creates one: what it refuses, for whom, from what risk", async () => {
    const user = userEvent.setup();
    show(<PoliciesCard canManage roles={[]} />);
    await user.click(screen.getByRole("button", { name: "Nouvelle politique" }));
    const form = await screen.findByTestId("policy-form");
    await user.type(within(form).getByLabelText("Nom"), "Admins seulement");
    await user.selectOptions(within(form).getByLabelText("Risque"), "high");
    await user.click(within(within(form).getByTestId("policy-roles")).getByLabelText("Membre"));
    await user.click(within(form).getByRole("button", { name: "Créer la politique" }));
    await waitFor(() =>
      expect(api.createPolicy).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Admins seulement",
          effect: "deny",
          actions: ["agent:run"],
          roles: ["member"],
          risk_at_least: "high",
          resource_types: ["capability"],
          priority: 50,
        }),
      ),
    );
  });
});

it("says every change in the history", async () => {
  show(<HistoryCard />);
  expect(await screen.findByTestId("governance-history")).toHaveTextContent("Rôle créé(e) · Tech Lead");
});
