/**
 * Sécurité & gouvernance (LEKA-402).
 *
 * What these protect: every role's permissions, as the API says them, the
 * reader's role said; the restricted entities, each with why, made visible
 * again only once confirmed; an entity restricted by searching it and saying
 * why — not without a reason; the trail of decisions, refusals first, each
 * with who, as which role, what, by which reason in words; a member sees the
 * matrix only. The overview (LEKA-438) says real figures, each opening the
 * tab it counts; the tab is in the URL.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import type { AccessDecision, AccessModel } from "@/lib/access";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const api = vi.hoisted(() => ({
  model: vi.fn(),
  restrictions: vi.fn(),
  restrict: vi.fn(),
  lift: vi.fn(),
  decisions: vi.fn(),
  search: vi.fn(),
  roles: vi.fn(),
  policies: vi.fn(),
  history: vi.fn(),
}));
const route = vi.hoisted(() => ({ search: "" }));
const people = vi.hoisted(() => ({ members: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/governance",
  useSearchParams: () => new URLSearchParams(route.search),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));
vi.mock("@/lib/access", async (original) => ({
  ...(await original<typeof import("@/lib/access")>()),
  access: api,
}));
vi.mock("@/lib/team", async (original) => ({
  ...(await original<typeof import("@/lib/team")>()),
  team: people,
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

const { GovernanceScreen } = await import("@/components/governance/governance-screen");

const ADMIN_PERMISSIONS = [
  "workspace:read",
  "intention:create",
  "entity:restrict",
  "entity:read_restricted",
  "access:read",
] as const;

function model(role: "member" | "admin", mine: readonly string[]): AccessModel {
  return {
    roles: [
      { role: "member", permissions: ["workspace:read", "intention:create"] },
      { role: "admin", permissions: [...ADMIN_PERMISSIONS] },
      { role: "owner", permissions: [...ADMIN_PERMISSIONS, "workspace:delete"] },
    ],
    permissions: [...ADMIN_PERMISSIONS, "workspace:delete"],
    writes: ["intention:create", "entity:restrict", "workspace:delete"],
    mine: [...mine],
    role,
  } as AccessModel;
}

const REFUSED: AccessDecision = {
  id: "d1",
  at: "2026-10-10T09:00:00Z",
  user_id: "u-member",
  role: "member",
  action: "workspace:read",
  permission: "workspace:read",
  resource_type: "entity",
  resource_id: "e1",
  decision: "deny",
  rule: "restriction",
  reason: "restricted",
  route: "GET /api/v1/knowledge/entities/e1",
  request_id: "r1",
};

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <GovernanceScreen />
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  route.search = "tab=access";
  api.roles.mockResolvedValue([]);
  api.policies.mockResolvedValue([]);
  api.history.mockResolvedValue([]);
  api.model.mockResolvedValue(model("admin", ADMIN_PERMISSIONS));
  api.restrictions.mockResolvedValue([
    {
      entity_id: "e1",
      name: "Billing API",
      type: "service",
      reason: "Données de paiement",
      restricted_by: "u-admin",
      restricted_at: "2026-10-10T08:00:00Z",
    },
  ]);
  api.decisions.mockResolvedValue([REFUSED]);
  api.search.mockResolvedValue({
    entities: [{ entity: { id: "e2", type: "service", key: "s", name: "Checkout", lifecycle: "active" } }],
  });
  api.restrict.mockResolvedValue({});
  api.lift.mockResolvedValue(undefined);
  people.members.mockResolvedValue([
    { id: "m1", user_id: "u-member", role: "member", email: "nora@acme.io", first_name: "Nora", last_name: "Diallo" },
  ]);
});

describe("governance", () => {
  it("says who may do what, the reader's role said", async () => {
    show();
    const matrix = await screen.findByTestId("access-matrix");
    expect(screen.getByText("Votre rôle : Admin")).toBeInTheDocument();
    const restrict = within(matrix).getByText("Restreindre une entité").closest("tr");
    expect(restrict).toHaveTextContent("écriture");
    expect(within(restrict as HTMLElement).getAllByLabelText("oui")).toHaveLength(2);
    expect(within(restrict as HTMLElement).getAllByLabelText("non")).toHaveLength(1);
  });

  it("lists the restricted entities and makes one visible again once confirmed", async () => {
    const user = userEvent.setup();
    show();
    const listed = await screen.findByTestId("restrictions");
    expect(listed).toHaveTextContent("Billing API · Données de paiement");
    await user.click(within(listed).getByRole("button", { name: "Rendre visible" }));
    await user.click(await screen.findByRole("button", { name: "Rendre visible" }));
    await waitFor(() => expect(api.lift).toHaveBeenCalledWith("e1"));
  });

  it("restricts an entity found by name, saying why", async () => {
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: "Restreindre une entité" }));
    const form = await screen.findByTestId("restrict-form");
    const button = within(form).getByRole("button", { name: "Restreindre" });
    expect(button).toBeDisabled();
    await user.type(within(form).getByLabelText("Entité"), "check");
    await user.click(await within(form).findByRole("button", { name: /Checkout/ }));
    await user.type(within(form).getByLabelText("Pourquoi"), "Projet confidentiel");
    await user.click(button);
    await waitFor(() =>
      expect(api.restrict).toHaveBeenCalledWith("e2", "Projet confidentiel"),
    );
  });

  it("sums it up in real figures, each opening what it counts", async () => {
    route.search = "";
    api.decisions.mockResolvedValue([
      { ...REFUSED, at: new Date().toISOString() },
      { ...REFUSED, id: "d0", at: "2026-01-05T09:00:00Z" },
    ]);
    show();
    const overview = await screen.findByTestId("governance-overview");
    await waitFor(() => expect(within(overview).getByTestId("governance-stat-restricted")).toHaveTextContent("1"));
    expect(within(overview).getByTestId("governance-stat-restricted")).toHaveAttribute("href", "/governance?tab=access");
    expect(within(overview).getByTestId("governance-stat-policies")).toHaveTextContent("0");
    expect(within(overview).getByTestId("governance-stat-refusals")).toHaveTextContent("Refus d'accès, 7 derniers jours");
    // Only this week's refusal counts.
    await waitFor(() =>
      expect(within(overview).getByTestId("governance-stat-refusals")).toHaveTextContent(/^1Refus/),
    );
    expect(overview).not.toHaveTextContent("/100");
    expect(screen.getByTestId("governance-tab-overview")).toHaveAttribute("aria-selected", "true");
  });

  it("shows the refusals first, each in words", async () => {
    route.search = "";
    show();
    const trail = await screen.findByTestId("decisions");
    expect(api.decisions).toHaveBeenCalledWith("deny");
    expect(trail).toHaveTextContent("Refusé");
    expect(trail).toHaveTextContent("Lire l'espace");
    expect(trail).toHaveTextContent("· entité e1");
    expect(await within(trail).findByText(/Nora Diallo · Membre · entité restreinte/)).toBeInTheDocument();
  });

  it("shows a member the matrix only", async () => {
    api.model.mockResolvedValue(model("member", ["workspace:read", "intention:create"]));
    show();
    await screen.findByTestId("access-matrix");
    expect(screen.queryByTestId("restrict-form")).not.toBeInTheDocument();
    expect(screen.queryByTestId("decisions")).not.toBeInTheDocument();
    expect(api.decisions).not.toHaveBeenCalled();
  });
});
