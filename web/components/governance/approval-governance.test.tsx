/**
 * Sécurité & gouvernance › Approbations (LEKA-404).
 *
 * What these protect: the policy per risk level as the API says it, saved
 * whole; the rules said in words, one removed keeping the others; an action
 * simulated, its risk and every reason said; freezes and waivers listed
 * with where they stand, granted saying why — a waiver with its actions,
 * environments and risk — and revoked once confirmed; delegations listed
 * and lent; the journal in words, LEKA's own moves said as LEKA's; a reader
 * who may not change the policy changes nothing; the tab reached from the
 * page.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import type { ApprovalPolicy, DecisionGovernanceEvent, GovernanceException } from "@/lib/decisions";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const ME = "u-admin";
const BOB = "u-member";
const api = vi.hoisted(() => ({
  policy: vi.fn(),
  setPolicy: vi.fn(),
  evaluate: vi.fn(),
  exceptions: vi.fn(),
  grantException: vi.fn(),
  revokeException: vi.fn(),
  delegations: vi.fn(),
  delegate: vi.fn(),
  revokeDelegation: vi.fn(),
  history: vi.fn(),
}));
const people = vi.hoisted(() => ({ members: vi.fn() }));
const access = vi.hoisted(() => ({ permissions: [] as string[] }));
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/governance",
  useSearchParams: () => new URLSearchParams(route.search),
  useRouter: () => ({ replace, push: vi.fn() }),
}));
const route = vi.hoisted(() => ({ search: "" }));
const replace = vi.hoisted(() => vi.fn());
vi.mock("@/lib/decisions", async (original) => ({
  ...(await original<typeof import("@/lib/decisions")>()),
  decisions: api,
}));
vi.mock("@/lib/team", async (original) => ({
  ...(await original<typeof import("@/lib/team")>()),
  team: people,
}));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => access.permissions,
  useCurrentUser: () => ({ id: ME }),
}));
vi.mock("@/lib/notify", () => ({ notify: notices }));
const accessApi = vi.hoisted(() => ({
  model: vi.fn(),
  restrictions: vi.fn(),
  restrict: vi.fn(),
  lift: vi.fn(),
  decisions: vi.fn(),
  search: vi.fn(),
}));
vi.mock("@/lib/access", async (original) => ({
  ...(await original<typeof import("@/lib/access")>()),
  access: accessApi,
}));

const { ApprovalGovernance } = await import("@/components/governance/approval-governance");
const { GovernanceScreen } = await import("@/components/governance/governance-screen");

const ADMIN = ["workspace:read", "workspace:update", "intention:read", "intention:approve"];
const NOW = Date.now();
const iso = (hours: number) => new Date(NOW + hours * 3_600_000).toISOString();

const POLICY: ApprovalPolicy = {
  approvals: { low: 1, medium: 1, high: 2, critical: 2 },
  separate: ["high", "critical"],
  production_raises: true,
  roles: { low: null, medium: null, high: null, critical: "owner" },
  valid_hours: { low: null, medium: null, high: 72, critical: 24 },
  escalate_hours: { low: null, medium: 48, high: 24, critical: 4 },
  rules: [
    {
      name: "irreversible",
      at_least: "high",
      actions: [],
      environments: [],
      target_types: [],
      target_criticality: [],
      reversible: false,
    },
    {
      name: "irreversible_in_production",
      at_least: "critical",
      actions: [],
      environments: ["production"],
      target_types: [],
      target_criticality: [],
      reversible: false,
    },
  ],
  customised: false,
};

const FREEZE: GovernanceException = {
  id: "x1",
  kind: "freeze",
  actions: [],
  environments: ["production"],
  targets: [],
  max_risk: "low",
  starts_at: iso(-1),
  ends_at: iso(24),
  reason: "Clôture comptable",
  granted_by: ME,
  revoked_at: null,
  revoked_by: null,
  active: true,
};

const EVENTS: DecisionGovernanceEvent[] = [
  {
    id: "e2",
    kind: "decision_escalated",
    by: null,
    at: iso(-1),
    subject_id: "d1",
    detail: { risk: "critical" },
  },
  {
    id: "e1",
    kind: "policy_changed",
    by: ME,
    at: iso(-2),
    subject_id: null,
    detail: { changed: ["roles", "rules"], before: {}, after: {} },
  },
];

function mount() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <ApprovalGovernance />
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  access.permissions = ADMIN;
  api.policy.mockResolvedValue(POLICY);
  api.setPolicy.mockResolvedValue({ ...POLICY, customised: true });
  api.exceptions.mockResolvedValue([FREEZE]);
  api.delegations.mockResolvedValue([
    {
      id: "g1",
      delegated_by: ME,
      delegated_to: BOB,
      max_risk: "medium",
      starts_at: iso(-1),
      ends_at: iso(48),
      reason: "Astreinte du week-end",
      revoked_at: null,
      revoked_by: null,
      active: true,
    },
  ]);
  api.history.mockResolvedValue(EVENTS);
  people.members.mockResolvedValue([
    { id: "m1", user_id: ME, role: "admin", email: "ada@acme.io", first_name: "Ada", last_name: "Admin", joined_at: iso(-900) },
    { id: "m2", user_id: BOB, role: "member", email: "bob@acme.io", first_name: "Bob", last_name: "Martin", joined_at: iso(-900) },
  ]);
});

describe("the approvals' governance", () => {
  it("shows the policy per risk and saves it whole", async () => {
    mount();
    const form = await screen.findByTestId("approval-policy");
    const critical = within(form).getByRole("row", { name: /Risque critique/ });
    expect(within(critical).getByRole("combobox", { name: "Rôle requis · Risque critique" })).toHaveValue(
      "owner",
    );
    const user = userEvent.setup();
    await user.selectOptions(
      within(form).getByRole("combobox", { name: "Validations · Risque élevé" }),
      "3",
    );
    await user.click(screen.getByTestId("approval-policy-save"));
    await waitFor(() => expect(api.setPolicy).toHaveBeenCalled());
    expect(api.setPolicy).toHaveBeenCalledWith({
      approvals: { low: 1, medium: 1, high: 3, critical: 2 },
      separate: ["high", "critical"],
      roles: { low: null, medium: null, high: null, critical: "owner" },
      valid_hours: { low: null, medium: null, high: 72, critical: 24 },
      escalate_hours: { low: null, medium: 48, high: 24, critical: 4 },
      production_raises: true,
    });
    expect(notices.success).toHaveBeenCalledWith({ title: "Politique enregistrée." });
  });

  it("says its rules in words; one removed keeps the others", async () => {
    mount();
    const rules = await screen.findByTestId("risk-rules");
    const prod = within(rules).getByText("Irréversible en production").closest("li")!;
    expect(prod).toHaveTextContent("toute action · en production · irréversible → au moins critique");
    const user = userEvent.setup();
    const first = within(rules).getByText("Irréversible").closest("li")!;
    await user.click(within(first).getByRole("button", { name: "Retirer" }));
    await waitFor(() =>
      expect(api.setPolicy).toHaveBeenCalledWith({ rules: [POLICY.rules[1]] }),
    );
  });

  it("simulates an action and says its risk, every reason", async () => {
    api.evaluate.mockResolvedValue({
      risk: "critical",
      reasons: [
        { code: "unknown", params: {} },
        { code: "rule", params: { rule: "irreversible_in_production", at_least: "critical" } },
      ],
      approvals: 2,
      separate: true,
      role: "owner",
      valid_hours: 24,
      escalate_hours: 4,
      frozen: true,
      waived: false,
      exceptions: [],
    });
    mount();
    const form = await screen.findByTestId("policy-simulate");
    const user = userEvent.setup();
    await user.selectOptions(within(form).getByRole("combobox", { name: "Action" }), "migrate");
    await user.click(within(form).getByRole("button", { name: "Évaluer" }));
    await waitFor(() =>
      expect(api.evaluate).toHaveBeenCalledWith({
        action: "migrate",
        environment: "production",
        risk: null,
        targets: [],
      }),
    );
    const verdict = await screen.findByTestId("policy-verdict");
    expect(verdict).toHaveTextContent("Risque critique");
    expect(verdict).toHaveTextContent("2 validations par une autre personne que le demandeur, dont un propriétaire");
    expect(verdict).toHaveTextContent("L'analyse ne dit pas son risque : moyen par défaut");
    expect(verdict).toHaveTextContent("Irréversible en production : au moins critique");
    expect(verdict).toHaveTextContent("Un gel la couvre");
  });

  it("lists freezes and waivers, grants one saying why, revokes once confirmed", async () => {
    api.grantException.mockResolvedValue({ ...FREEZE, id: "x2", kind: "waiver" });
    api.revokeException.mockResolvedValue({ ...FREEZE, revoked_at: iso(0) });
    mount();
    const list = await screen.findByTestId("governance-exceptions");
    const freeze = within(list).getByText("Clôture comptable").closest("li")!;
    expect(freeze).toHaveTextContent("Gel");
    expect(freeze).toHaveTextContent("En cours");
    expect(freeze).toHaveTextContent("production");
    expect(freeze).toHaveTextContent("Ada Admin");

    const user = userEvent.setup();
    const form = screen.getByTestId("exception-form");
    await user.click(within(form).getByRole("radio", { name: "Dérogation" }));
    await user.type(within(form).getByRole("textbox", { name: "Pourquoi" }), "Redémarrages de routine");
    const until = form.querySelectorAll("input[type=datetime-local]")[1] as HTMLInputElement;
    await user.type(until, "2026-12-01T08:00");
    await user.click(within(form).getByRole("checkbox", { name: "Redémarrer" }));
    await user.type(within(form).getByRole("textbox", { name: /Environnements/ }), "production");
    await user.selectOptions(within(form).getByRole("combobox", { name: "Jusqu'au risque" }), "medium");
    await user.click(within(form).getByRole("button", { name: "Accorder" }));
    await waitFor(() => expect(api.grantException).toHaveBeenCalled());
    expect(api.grantException).toHaveBeenCalledWith({
      kind: "waiver",
      reason: "Redémarrages de routine",
      starts_at: null,
      ends_at: new Date("2026-12-01T08:00").toISOString(),
      actions: ["restart"],
      environments: ["production"],
      targets: [],
      max_risk: "medium",
    });
    expect(notices.success).toHaveBeenCalledWith({ title: "Dérogation accordée." });

    await user.click(within(freeze).getByRole("button", { name: "Révoquer" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Révoquer ce gel ?");
    await user.click(within(dialog).getByRole("button", { name: "Révoquer" }));
    await waitFor(() => expect(api.revokeException).toHaveBeenCalledWith("x1"));
  });

  it("lists delegations and lends one", async () => {
    api.delegate.mockResolvedValue({});
    mount();
    const list = await screen.findByTestId("delegations");
    await waitFor(() =>
      expect(list).toHaveTextContent("Ada Admin → Bob Martin · jusqu'au risque moyen"),
    );
    expect(list).toHaveTextContent("Astreinte du week-end");
    const user = userEvent.setup();
    const form = screen.getByTestId("delegation-form");
    await user.selectOptions(within(form).getByRole("combobox", { name: "À qui" }), BOB);
    await user.selectOptions(within(form).getByRole("combobox", { name: "Jusqu'au risque" }), "high");
    await user.type(form.querySelector("input[type=datetime-local]")!, "2026-12-01T08:00");
    await user.type(within(form).getByRole("textbox", { name: "Pourquoi" }), "Congés");
    await user.click(within(form).getByRole("button", { name: "Déléguer" }));
    await waitFor(() =>
      expect(api.delegate).toHaveBeenCalledWith({
        to: BOB,
        max_risk: "high",
        reason: "Congés",
        ends_at: new Date("2026-12-01T08:00").toISOString(),
        starts_at: null,
      }),
    );
  });

  it("says the journal in words, LEKA's own moves as LEKA's", async () => {
    mount();
    const journal = await screen.findByTestId("governance-journal");
    const [escalated, changed] = within(journal).getAllByRole("listitem");
    expect(escalated).toHaveTextContent("Décision escaladée · Risque critique");
    expect(escalated).toHaveTextContent("LEKA");
    expect(changed).toHaveTextContent("Politique modifiée · changé : rôles, règles");
    await waitFor(() => expect(changed).toHaveTextContent("Ada Admin"));
  });

  it("a reader who may not change it changes nothing", async () => {
    access.permissions = ["workspace:read", "intention:read"];
    mount();
    const form = await screen.findByTestId("approval-policy");
    expect(within(form).getByRole("combobox", { name: "Validations · Risque élevé" })).toBeDisabled();
    expect(form).toHaveTextContent("Seuls les administrateurs modifient la politique.");
    expect(screen.queryByTestId("exception-form")).not.toBeInTheDocument();
    expect(screen.queryByTestId("delegation-form")).not.toBeInTheDocument();
    expect(screen.queryByTestId("risk-rule-form")).not.toBeInTheDocument();
  });

  it("is a tab of its own, in the URL", async () => {
    route.search = "tab=access";
    accessApi.model.mockResolvedValue({
      roles: [{ role: "admin", permissions: ["access:read"] }],
      permissions: ["access:read"],
      writes: [],
      mine: [],
      role: "admin",
    });
    render(
      <QueryClientProvider client={makeQueryClient()}>
        <LocaleProvider>
          <ConfirmProvider>
            <GovernanceScreen />
          </ConfirmProvider>
        </LocaleProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("access-matrix")).toBeVisible();
    expect(screen.queryByTestId("approval-governance")).not.toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Approbations" }));
    expect(replace).toHaveBeenCalledWith("/governance?tab=approvals", { scroll: false });
  });
});
