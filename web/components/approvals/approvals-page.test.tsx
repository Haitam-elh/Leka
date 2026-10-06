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
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmProvider } from "@/components/interactions/confirm";
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

vi.mock("@/lib/enrichment", async (original) => ({
  ...(await original<typeof import("@/lib/enrichment")>()),
  enrichment: api,
}));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
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
});

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
    expect(said({ code: "enrichment.summary", statement: "What auth-service does." })).toEqual({
      title: "What auth-service does.",
      why: null,
    });
  });
});
