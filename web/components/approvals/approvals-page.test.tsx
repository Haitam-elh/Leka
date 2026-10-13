/**
 * À valider (LEKA-380): what LEKA proposes to add to the company model,
 * waiting on someone — laid out as mockup 09, with the workspace's own
 * proposals.
 *
 * What these protect: the figures are the workspace's — waiting,
 * accepted (by the policy among them), rejected, withdrawn; each proposal
 * is worded from its code, with why and how sure, filtered by state, type
 * and words; opened, it says what it would change — the relationship, or
 * the attribute now and proposed, a warning when it replaces a source's
 * word — what shows it and where it was read, and every decision taken;
 * who may approve accepts — an override only once confirmed — rejects with
 * a reason, sends back what was rejected; nobody else does; with nothing
 * ever proposed, it says what will come here.
 *
 * And the conflicts between sources (LEKA-382), in the same queue: worded
 * with what LEKA recommends; opened, every side with its sources — how
 * much each is believed, when it said it — the side recommended; who may
 * approve keeps a side, remembering its source if they say so, says it is
 * no contradiction, reopens what was decided.
 *
 * And the decisions on what intentions ask to do (LEKA-390): listed with
 * their impact; opened, the actions proposed, how many must approve, every
 * vote; who may approve approves — asked first — rejects saying why,
 * modifies where it runs; the asker kept apart by the policy, and anyone
 * who may not approve, are told why they cannot.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
import type { ConflictDetail } from "@/lib/conflicts";
import type { Candidate, CandidateDetail, EnrichmentSummary } from "@/lib/enrichment";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const api = vi.hoisted(() => ({
  summary: vi.fn(),
  candidates: vi.fn(),
  candidate: vi.fn(),
  accept: vi.fn(),
  reject: vi.fn(),
  reprocess: vi.fn(),
}));
const permissions = vi.hoisted(() => ({ value: ["workspace:read", "intention:approve"] }));
const disputes = vi.hoisted(() => ({
  list: vi.fn(),
  one: vi.fn(),
  summary: vi.fn(),
  resolve: vi.fn(),
  dismiss: vi.fn(),
  reopen: vi.fn(),
}));

vi.mock("@/lib/conflicts", async (original) => ({
  ...(await original<typeof import("@/lib/conflicts")>()),
  conflicts: disputes,
}));

vi.mock("@/lib/enrichment", async (original) => ({
  ...(await original<typeof import("@/lib/enrichment")>()),
  enrichment: api,
}));
const choices = vi.hoisted(() => ({
  queue: vi.fn(),
  summary: vi.fn(),
  policy: vi.fn(),
  of: vi.fn(),
  vote: vi.fn(),
}));
const me = vi.hoisted(() => ({ id: "9c3bc5ff-a12e-5e92-a5ae-ad6da2029a41" }));
const notices = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }));

vi.mock("@/lib/decisions", async (original) => ({
  ...(await original<typeof import("@/lib/decisions")>()),
  decisions: choices,
}));
vi.mock("@/lib/notify", () => ({ notify: notices }));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
  useCurrentUser: () => me,
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/approvals" }));

const { ApprovalsPage } = await import("@/components/approvals/approvals-page");
const { wordCandidate } = await import("@/components/approvals/words");
const { DICTIONARIES } = await import("@/lib/i18n/dictionaries");

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
const PG = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const PLATFORM = "1c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const USERS = "2c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const REPO = "3c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const CART = "4c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";

function candidate(overrides: Partial<CandidateDetail>): CandidateDetail {
  return {
    id: crypto.randomUUID(),
    analyzer: "enrich_owner",
    family: "organisation",
    code: "enrichment.owner",
    method: "rules",
    kind: "relationship",
    subject: { type: "entity", id: PG, name: "postgres-prod", kind: "database" },
    relationship: "owned_by",
    start: { type: "entity", id: PG, name: "postgres-prod", kind: "database" },
    end: { type: "entity", id: PLATFORM, name: "Platform", kind: "team" },
    attribute: null,
    value: null,
    current: null,
    overrides: false,
    statement: "Platform likely owns postgres-prod.",
    params: { name: "postgres-prod", team: "Platform", how: "maintainers", members: 2, maintainers: 2 },
    confidence: 0.85,
    status: "proposed",
    decided_via: null,
    decided_at: null,
    first_seen_at: minutesAgo(60),
    last_seen_at: minutesAgo(5),
    occurrences: 1,
    evidence: [
      { kind: "entity", id: "p1", name: "Thomas Berger", detail: "maintains postgres-prod; a member of Platform" },
    ],
    provenance: { analyzer: "enrich_owner", sources: ["github"] },
    decided_by: null,
    reason: null,
    history: [],
    ...overrides,
  };
}

const OWNER = candidate({});
const CODE = candidate({
  analyzer: "enrich_code",
  family: "relationship",
  code: "enrichment.code",
  subject: { type: "entity", id: USERS, name: "user-service", kind: "service" },
  start: { type: "entity", id: REPO, name: "acme/user-service", kind: "repository" },
  end: { type: "entity", id: USERS, name: "user-service", kind: "service" },
  relationship: "part_of",
  params: { name: "user-service", repository: "acme/user-service", match: "same" },
  confidence: 0.8,
});
const CRITICAL = candidate({
  analyzer: "enrich_criticality",
  family: "semantic",
  code: "enrichment.criticality",
  kind: "attribute",
  subject: { type: "entity", id: CART, name: "cart", kind: "service" },
  start: null,
  end: null,
  relationship: null,
  attribute: "criticality",
  value: "critical",
  current: "low",
  overrides: true,
  params: { name: "cart", level: "critical", current: "low", from: "application", application: "checkout" },
  confidence: 0.75,
});
const SUMMARY: EnrichmentSummary = {
  proposed: 3,
  accepted: 2,
  rejected: 1,
  withdrawn: 0,
  by_policy: 1,
  families: { organisation: 1, relationship: 1, semantic: 1 },
};
const BY_ID = new Map([OWNER, CODE, CRITICAL].map((c) => [c.id, c]));
const GITHUB = "5c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const DATADOG = "6c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";

function conflict(overrides: Partial<ConflictDetail> = {}): ConflictDetail {
  return {
    id: crypto.randomUUID(),
    kind: "attribute",
    subject: { type: "entity", id: crypto.randomUUID(), name: "payment-api", kind: "service" },
    about: "sla",
    relationship: null,
    chosen: "99.95",
    sides: [
      {
        value: "99.95",
        ref_id: null,
        origin: null,
        sources: [
          {
            source_id: GITHUB,
            kind: "github",
            name: "acme/backend",
            status: "active",
            observed_at: minutesAgo(60 * 24),
            authority: 0.85,
            rule: null,
          },
        ],
        authority: 0.85,
        freshness: 0.5,
        corroboration: 0.333,
        score: 0.667,
      },
      {
        value: "99.9",
        ref_id: null,
        origin: null,
        sources: [
          {
            source_id: DATADOG,
            kind: "datadog",
            name: "acme-eu",
            status: "active",
            observed_at: minutesAgo(60 * 24),
            authority: 0.7,
            rule: null,
          },
        ],
        authority: 0.7,
        freshness: 0.5,
        corroboration: 0.333,
        score: 0.585,
      },
    ],
    recommendation: { side: 0, strength: "weak", reasons: ["authority", "chosen"], margin: 0.082 },
    statement: "payment-api's sources disagree on sla.",
    status: "open",
    resolution: null,
    first_seen_at: minutesAgo(60),
    last_seen_at: minutesAgo(5),
    occurrences: 1,
    provenance: { analyzer: "conflicts", sources: ["datadog", "github"] },
    history: [],
    ...overrides,
  };
}

const SLA = conflict();

function mount() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <ConfirmProvider>
          <ApprovalsPage />
        </ConfirmProvider>
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions.value = ["workspace:read", "intention:approve"];
  api.summary.mockResolvedValue(SUMMARY);
  api.candidates.mockImplementation(async (status: string) => ({
    data: status === "proposed" ? [OWNER, CODE, CRITICAL] : [],
    next_cursor: null,
  }));
  api.candidate.mockImplementation(async (id: string) => BY_ID.get(id));
  api.accept.mockImplementation(async (id: string) => ({ ...BY_ID.get(id), status: "accepted" }));
  api.reject.mockImplementation(async (id: string) => ({ ...BY_ID.get(id), status: "rejected" }));
  api.reprocess.mockResolvedValue({ candidate: OWNER, queued: true });
  disputes.summary.mockResolvedValue({ open: 0, resolved: 0, dismissed: 0, gone: 0 });
  disputes.list.mockResolvedValue({ data: [], next_cursor: null });
  disputes.one.mockResolvedValue(SLA);
  disputes.resolve.mockImplementation(async () => ({ ...SLA, status: "resolved" }));
  disputes.dismiss.mockImplementation(async () => ({ ...SLA, status: "dismissed" }));
  disputes.reopen.mockImplementation(async () => SLA);
  choices.summary.mockResolvedValue({
    proposed: 0,
    approved: 0,
    rejected: 0,
    changes_requested: 0,
    superseded: 0,
  });
  choices.queue.mockResolvedValue({ data: [] });
  choices.vote.mockImplementation(async () => ({ ...RESTART.decision, status: "approved" }));
});

const INTENTION = "5c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const BILLING = "6c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const ASKER = "7c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";

function decisionItem(overrides: Record<string, unknown> = {}) {
  return {
    intention: {
      id: INTENTION,
      title: "Redémarre Billing API en production",
      status: "awaiting_decision",
      kind: "change",
      created_by: ASKER,
      summary: null,
    },
    decision: {
      id: "8c3bc5ff-a12e-5e92-a5ae-ad6da2029a41",
      intention_id: INTENTION,
      number: 1,
      status: "proposed" as const,
      open: true,
      risk: "medium" as const,
      analysis_risk: "medium",
      revision: 1,
      required_approvals: 1,
      separate_asker: false,
      approvers: [],
      proposals: [
        {
          id: "restart",
          action: "restart",
          targets: [{ id: BILLING, name: "Billing API", type: "service" }],
          environment: "production",
          constraints: [{ kind: "no_downtime", value: true }],
          reversible: true,
        },
      ],
      analysis_id: null,
      context_version: 2,
      asked_by: ASKER,
      created_at: minutesAgo(30),
      decided_at: null,
      votes: [],
      ...overrides,
    },
  };
}
const RESTART = decisionItem();

function withDecision(item = RESTART) {
  choices.summary.mockResolvedValue({
    proposed: 1,
    approved: 0,
    rejected: 0,
    changes_requested: 0,
    superseded: 0,
  });
  choices.queue.mockImplementation(async (status: string) => ({
    data: status === "proposed" ? [item] : [],
  }));
}

async function openDecision() {
  const user = userEvent.setup();
  const table = await screen.findByRole("table");
  await user.click(within(table).getByText(/Redémarrer Billing API · production/));
  return { user, panel: await screen.findByTestId("decision-panel") };
}

function withConflict() {
  disputes.summary.mockResolvedValue({ open: 1, resolved: 0, dismissed: 0, gone: 0 });
  disputes.list.mockImplementation(async (status: string) => ({
    data: status === "open" ? [SLA] : [],
    next_cursor: null,
  }));
}

async function open(name: RegExp) {
  const user = userEvent.setup();
  const table = await screen.findByRole("table");
  await user.click(within(table).getByText(name));
  return { user, panel: await screen.findByTestId("candidate-panel") };
}

describe("À valider", () => {
  it("says the workspace's figures and lists what waits, worded", async () => {
    mount();

    const stats = await screen.findByTestId("approvals-stats");
    expect(stats).toHaveTextContent("3En attente");
    expect(stats).toHaveTextContent("2Validésdont 1 automatiquement");
    expect(stats).toHaveTextContent("1Refusés");
    const table = await screen.findByRole("table");
    expect(table).toHaveTextContent("Platform est responsable de postgres-prod");
    expect(table).toHaveTextContent("2 des 2 personnes qui le maintiennent sont membres de Platform");
    expect(table).toHaveTextContent("acme/user-service est le code de user-service");
    expect(table).toHaveTextContent("Criticité de cart : critique au lieu de faible");
    expect(table).toHaveTextContent("85 %");
    expect(api.candidates).toHaveBeenCalledWith("proposed");
  });

  it("narrows by type, by words, and by state", async () => {
    const user = userEvent.setup();
    mount();
    const table = await screen.findByRole("table");

    await user.click(screen.getByRole("button", { name: /Sémantique/ }));
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: /^Tous/ }));
    await user.type(screen.getByPlaceholderText("Rechercher un élément…"), "user-service");
    await waitFor(() => expect(table).not.toHaveTextContent("postgres-prod"));
    expect(table).toHaveTextContent("acme/user-service");

    await user.click(screen.getByRole("button", { name: "Refusé" }));
    await waitFor(() => expect(api.candidates).toHaveBeenCalledWith("rejected"));
    expect(await screen.findByText("Aucune proposition dans cet état.")).toBeVisible();
  });

  it("opens a proposal: what it changes, what shows it, where it was read", async () => {
    mount();
    const { panel } = await open(/acme\/user-service est le code/);

    expect(within(panel).getByTestId("candidate-change")).toHaveTextContent(
      "acme/user-service fait partie de user-service",
    );
    expect(within(panel).getByRole("link", { name: "user-service" })).toHaveAttribute(
      "href",
      `/environment/services/${USERS}`,
    );
    expect(panel).toHaveTextContent("LEKA · analyse « Code d'un service »");
    expect(panel).toHaveTextContent("80 %");
    expect(panel).toHaveTextContent("GitHub");
    expect(within(panel).getByTestId("candidate-evidence")).toHaveTextContent("Thomas Berger");
  });

  it("accepts, and a replacement of a source's word only once confirmed", async () => {
    mount();
    const { user, panel } = await open(/Criticité de cart/);
    const change = within(panel).getByTestId("candidate-change");
    expect(change).toHaveTextContent("Aujourd'huifaible");
    expect(change).toHaveTextContent("Proposécritique");
    expect(panel).toHaveTextContent("Remplace ce qu'une source déclare");

    await user.click(within(panel).getByRole("button", { name: "Valider" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Remplacer ce que dit la source ?");
    expect(api.accept).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Valider et remplacer" }));
    await waitFor(() =>
      expect(api.accept).toHaveBeenCalledWith(CRITICAL.id, { override: true, reason: null }),
    );
    // Said in the panel, not in a toast over its buttons.
    expect(await within(panel).findByRole("status")).toHaveTextContent("Validé.");
  });

  it("rejects with a reason, and sends back what was rejected", async () => {
    const rejected = candidate({
      ...OWNER,
      status: "rejected",
      decided_at: minutesAgo(1),
      history: [
        { status: "rejected", via: "person", by: "me", at: minutesAgo(1), reason: "Owned by the DBA team" },
      ],
    });
    api.reject.mockImplementation(async () => {
      api.candidate.mockResolvedValue(rejected);
      return rejected;
    });
    mount();
    const { user, panel } = await open(/Platform est responsable/);

    await user.click(within(panel).getByRole("button", { name: "Refuser" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByRole("textbox"), "Owned by the DBA team");
    await user.click(within(dialog).getByRole("button", { name: "Refuser" }));
    await waitFor(() =>
      expect(api.reject).toHaveBeenCalledWith(OWNER.id, { reason: "Owned by the DBA team" }),
    );

    await user.click(within(panel).getByRole("tab", { name: "Décisions" }));
    expect(await within(panel).findByTestId("candidate-history")).toHaveTextContent(
      "Refusé par une personne",
    );
    await user.click(await within(panel).findByRole("button", { name: "Retraiter" }));
    await waitFor(() => expect(api.reprocess).toHaveBeenCalledWith(OWNER.id));
  });

  it("lets nobody else decide", async () => {
    permissions.value = ["workspace:read"];
    mount();
    const { panel } = await open(/Platform est responsable/);

    expect(panel).toHaveTextContent("Seul un administrateur peut décider.");
    expect(within(panel).queryByRole("button", { name: "Valider" })).not.toBeInTheDocument();
  });

  it("says what will come here when nothing was ever proposed", async () => {
    api.summary.mockResolvedValue({
      proposed: 0,
      accepted: 0,
      rejected: 0,
      withdrawn: 0,
      by_policy: 0,
      families: {},
    });
    mount();

    expect(await screen.findByText("Rien à valider pour le moment.")).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});

describe("À valider: the conflicts between sources", () => {
  it("lists a conflict among the proposals, with what LEKA recommends", async () => {
    withConflict();
    mount();

    const stats = await screen.findByTestId("approvals-stats");
    expect(stats).toHaveTextContent("4En attente");
    const table = await screen.findByRole("table");
    expect(table).toHaveTextContent("SLA de payment-api : 99.95 ou 99.9");
    expect(table).toHaveTextContent("LEKA recommande 99.95 · de peu");
    expect(screen.getByRole("button", { name: /Conflits/ })).toBeVisible();
    expect(disputes.list).toHaveBeenCalledWith("open");
  });

  it("weighs every side and keeps the one chosen, remembering its source", async () => {
    withConflict();
    mount();
    const user = userEvent.setup();
    await user.click(within(await screen.findByRole("table")).getByText(/SLA de payment-api/));
    const panel = await screen.findByTestId("conflict-panel");

    expect(panel).toHaveTextContent("Le modèle affiche 99.95");
    const sides = within(panel).getByTestId("conflict-sides");
    expect(sides).toHaveTextContent("99.95Recommandé");
    expect(sides).toHaveTextContent("acme/backend· Fiabilité 85 %· dit il y a 1 j");
    expect(sides).toHaveTextContent("acme-eu· Fiabilité 70 %");
    expect(panel).toHaveTextContent("source plus fiable, déjà affiché");

    await user.click(within(panel).getByRole("checkbox"));
    await user.click(within(panel).getByTestId("keep-1"));
    await waitFor(() =>
      expect(disputes.resolve).toHaveBeenCalledWith(SLA.id, {
        side: 1,
        reason: null,
        remember: true,
      }),
    );
    expect(await within(panel).findByRole("status")).toHaveTextContent("Tranché.");
  });

  it("says it is no contradiction", async () => {
    withConflict();
    mount();
    const user = userEvent.setup();
    await user.click(within(await screen.findByRole("table")).getByText(/SLA de payment-api/));
    const panel = await screen.findByTestId("conflict-panel");

    await user.click(within(panel).getByRole("button", { name: "Ce n'est pas une contradiction" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByRole("textbox"), "Two SLOs");
    await user.click(within(dialog).getByRole("button", { name: "Écarter" }));
    await waitFor(() =>
      expect(disputes.dismiss).toHaveBeenCalledWith(SLA.id, { reason: "Two SLOs" }),
    );
  });

  it("reopens what was decided, its history kept", async () => {
    const settled = conflict({
      id: SLA.id,
      status: "resolved",
      resolution: { side: 1, value: "99.9", via: "person", by: "me", at: minutesAgo(2), reason: null },
      history: [{ status: "resolved", via: "person", by: "me", at: minutesAgo(2), value: "99.9" }],
    });
    disputes.summary.mockResolvedValue({ open: 0, resolved: 1, dismissed: 0, gone: 0 });
    disputes.list.mockImplementation(async (status: string) => ({
      data: status === "resolved" ? [settled] : [],
      next_cursor: null,
    }));
    disputes.one.mockResolvedValue(settled);
    mount();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Validé" }));
    await user.click(within(await screen.findByRole("table")).getByText(/SLA de payment-api/));
    const panel = await screen.findByTestId("conflict-panel");

    expect(within(panel).getByTestId("conflict-sides")).toHaveTextContent("99.9Retenu");
    expect(panel).toHaveTextContent("Le modèle affichera ce choix à sa prochaine construction.");
    await user.click(within(panel).getByRole("button", { name: "Rouvrir" }));
    await waitFor(() => expect(disputes.reopen).toHaveBeenCalledWith(SLA.id));
    await user.click(within(panel).getByRole("tab", { name: "Décisions" }));
    expect(await within(panel).findByTestId("conflict-history")).toHaveTextContent(
      "Tranché · 99.9 par une personne",
    );
  });

  it("lets nobody else settle it", async () => {
    withConflict();
    permissions.value = ["workspace:read"];
    mount();
    const user = userEvent.setup();
    await user.click(within(await screen.findByRole("table")).getByText(/SLA de payment-api/));
    const panel = await screen.findByTestId("conflict-panel");
    expect(panel).toHaveTextContent("Seul un administrateur peut décider.");
    expect(within(panel).queryByTestId("keep-0")).not.toBeInTheDocument();
  });
});

describe("a proposal's words", () => {
  const t = DICTIONARIES.fr;
  const said = (overrides: Partial<Candidate>) => wordCandidate(t, candidate(overrides));

  it("tells every family apart, and falls back on the English sentence", () => {
    expect(
      said({ code: "enrichment.runtime", params: { name: "payment-api", resource: "payment-api-prod" } }),
    ).toEqual({ title: "payment-api tourne sur payment-api-prod", why: "D'après le nom de la ressource" });
    expect(
      said({ params: { name: "auth-service", team: "Identity", how: "repository", repository: "acme/auth" } }),
    ).toEqual({ title: "Identity est responsable de auth-service", why: "Identity possède acme/auth, son code" });
    expect(
      said({
        code: "enrichment.application",
        params: { name: "order-service", application: "checkout", how: "neighbours", count: 2, of: 2 },
      }),
    ).toEqual({
      title: "order-service fait partie de checkout",
      why: "2 des 2 services avec lesquels il travaille en font partie",
    });
    expect(
      said({ code: "enrichment.criticality", params: { name: "postgres-prod", level: "high", from: "reliance", relying: 6 } }),
    ).toEqual({ title: "Criticité de postgres-prod : élevée", why: "6 éléments en dépendent" });
    expect(
      said({ code: "enrichment.description", params: { name: "auth-service", repository: "acme/auth" } }),
    ).toEqual({ title: "Description de auth-service", why: "D'après le dépôt acme/auth" });
    // Written by a model (LEKA-394): who wrote it, from how much, to check.
    expect(
      said({ code: "enrichment.summary", params: { name: "auth-service", model: "gemini-3.8-flash", facts: 3 } }),
    ).toEqual({
      title: "Description de auth-service",
      why: "Rédigée par Gemini 3.8 Flash d'après 3 faits que LEKA connaît : à vérifier",
    });
    expect(said({ code: "enrichment.unknown", statement: "What auth-service does." })).toEqual({
      title: "What auth-service does.",
      why: null,
    });
  });
});

describe("À valider — decisions (LEKA-390)", () => {
  it("lists an action asked among what waits, with its impact, and opens it", async () => {
    withDecision();
    mount();
    const table = await screen.findByRole("table");
    const row = within(table).getByText(/Redémarrer Billing API · production/).closest("tr");
    expect(row).toHaveTextContent("Risque moyen · 1 validation requise");
    expect(row).toHaveTextContent("Moyen");
    expect(row).toHaveTextContent("À valider");

    const { panel } = await openDecision();
    expect(panel).toHaveTextContent("Redémarre Billing API en production");
    expect(within(panel).getByTestId("decision-requirement")).toHaveTextContent(
      "1 validation requise · 0 sur 1",
    );
    const [proposal] = within(panel).getAllByTestId("decision-proposal");
    expect(proposal).toHaveTextContent("Redémarrer");
    expect(proposal).toHaveTextContent("Billing API");
    expect(proposal).toHaveTextContent("en production");
    expect(proposal).toHaveTextContent("Réversible");
    expect(proposal).toHaveTextContent("À respecter : Sans interruption");
    expect(panel).toHaveTextContent("Vous gardez le contrôle");
    expect(panel).toHaveTextContent("Aucun vote pour l'instant.");
  });

  it("approves once asked, saying what it opens the way to", async () => {
    withDecision();
    mount();
    const { user, panel } = await openDecision();
    await user.click(within(panel).getByTestId("decision-approve"));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Redémarrer · Billing API · production");
    await user.click(within(dialog).getByRole("button", { name: "Valider" }));
    await waitFor(() => expect(choices.vote).toHaveBeenCalledWith(INTENTION, "approve", {}));
    expect(notices.success).toHaveBeenCalledWith({ title: "Votre validation est enregistrée." });
  });

  it("rejects saying why — not without", async () => {
    withDecision();
    mount();
    const { user, panel } = await openDecision();
    await user.click(within(panel).getByTestId("decision-reject"));
    let dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Refuser" }));
    expect(choices.vote).not.toHaveBeenCalled();
    expect(notices.error).toHaveBeenCalledWith({
      title: "Dites pourquoi : c'est gardé avec la décision.",
    });

    await user.click(within(panel).getByTestId("decision-reject"));
    dialog = await screen.findByRole("alertdialog");
    await user.type(within(dialog).getByRole("textbox"), "Pas pendant les soldes.");
    await user.click(within(dialog).getByRole("button", { name: "Refuser" }));
    await waitFor(() =>
      expect(choices.vote).toHaveBeenCalledWith(INTENTION, "reject", {
        reason: "Pas pendant les soldes.",
      }),
    );
  });

  it("modifies where it runs, then approves", async () => {
    withDecision();
    mount();
    const { user, panel } = await openDecision();
    await user.click(within(panel).getByTestId("decision-modify-open"));
    const environment = within(panel).getByTestId("decision-modify-environment");
    await user.clear(environment);
    await user.type(environment, "staging");
    await user.type(within(panel).getByTestId("decision-modify-reason"), "D'abord en staging.");
    await user.click(within(panel).getByTestId("decision-modify-submit"));
    await waitFor(() =>
      expect(choices.vote).toHaveBeenCalledWith(INTENTION, "modify", {
        environment: "staging",
        keep: ["restart"],
        reason: "D'abord en staging.",
      }),
    );
  });

  it("tells the asker the policy wants someone else, and a member they cannot decide", async () => {
    withDecision(
      decisionItem({ separate_asker: true, asked_by: me.id, risk: "high", required_approvals: 2 }),
    );
    mount();
    const { panel } = await openDecision();
    expect(within(panel).queryByTestId("decision-approve")).not.toBeInTheDocument();
    expect(panel).toHaveTextContent(
      "La politique demande qu'une autre personne que vous valide cette action.",
    );
    expect(within(panel).getByTestId("decision-requirement")).toHaveTextContent(
      "2 validations requises par une autre personne que le demandeur · 0 sur 2",
    );
  });
});
