/**
 * The "Contexte" tab of an entity's sheet (LEKA-370).
 *
 * What these protect: with no context yet, it says so and assembles one
 * around the entity, as asked — why, how far; a context shows its figures,
 * its elements in order, each saying why it is there and, opened, where it
 * came from — its sources, the key or the record, a deleted source still
 * said, stated or inferred by which rule, what LEKA reads of it; its
 * versions, any one shown again, two compared; reassembling says whether
 * anything changed; a failed version says why; a role that may not
 * assemble reads, and is offered nothing it cannot do.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type {
  AssembledContext,
  ContextDiff,
  ContextElement,
  ContextRead,
  ContextVersion,
} from "@/lib/context";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const api = {
  ofEntity: vi.fn(),
  versions: vi.fn(),
  assembled: vi.fn(),
  diff: vi.fn(),
  create: vi.fn(),
  refresh: vi.fn(),
  archive: vi.fn(),
};
const permissions: { value: string[] } = { value: [] };
const notify = { success: vi.fn(), error: vi.fn(), info: vi.fn() };

vi.mock("@/lib/context", async (original) => ({
  ...(await original<typeof import("@/lib/context")>()),
  contexts: api,
}));
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
}));
vi.mock("@/lib/notify", () => ({ notify }));

const { EntityContext } = await import("@/components/environment/entity-context");

const BILLING = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const CHECKOUT = "1c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const LEDGER = "2c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const DEPENDS = "3c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const DEPLOYED = "4c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const CONTEXT = "5c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const CATALOGUE = "6c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const GONE = "7c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const NOW = new Date().toISOString();

type Provenance = ContextElement["provenance"];

function provenance(over: Partial<Provenance> = {}): Provenance {
  return {
    origin: "stated",
    rule: null,
    confidence: 0.9,
    sources: [],
    evidence: [],
    inferred_from: [],
    attributes: {},
    conflicts: [],
    first_seen_at: NOW,
    last_seen_at: NOW,
    changed_at: null,
    ...over,
  };
}

function entity(
  id: string,
  name: string,
  type: string,
  position: number,
  reason: ContextElement["reason"],
  said: Partial<Provenance> = {},
  relevance: number | null = null,
): ContextElement {
  return {
    position,
    kind: "entity",
    ref_id: id,
    ref_type: type,
    label: name,
    entity: {
      type,
      key: `${type}:${name.toLowerCase()}`,
      name,
      attributes: {},
      lifecycle: "active",
      version: 1,
      confidence: 0.9,
      quality: null,
    },
    relationship: null,
    provenance: provenance(said),
    reason,
    relevance,
    text: `${type} "${name}"`,
  };
}

function tie(
  id: string,
  from: [string, string],
  to: [string, string],
  position: number,
  said: Partial<Provenance> = {},
): ContextElement {
  return {
    position,
    kind: "relationship",
    ref_id: id,
    ref_type: "depends_on",
    label: `${from[1]} → ${to[1]}`,
    entity: null,
    relationship: {
      type: "depends_on",
      start: { id: from[0], type: "service", key: `service:${from[1]}`, name: from[1] },
      end: { id: to[0], type: "service", key: `service:${to[1]}`, name: to[1] },
      confidence: said.confidence ?? 0.9,
      origin: said.origin ?? "stated",
      rule: said.rule ?? "stated",
      cross_source: false,
      attributes: {},
    },
    provenance: provenance(said),
    reason: {
      strategy: "hybrid",
      role: "tie",
      depth: 1,
      root: null,
      via: null,
      retrievers: [],
    },
    relevance: null,
    text: `"${from[1]}" depends_on "${to[1]}"`,
  };
}

const ELEMENTS: ContextElement[] = [
  entity(
    BILLING,
    "Billing API",
    "service",
    0,
    {
      strategy: "hybrid",
      role: "root",
      depth: 0,
      root: BILLING,
      via: null,
      retrievers: [{ retriever: "search", rank: 1, score: 0.0909, detail: "billing, api" }],
    },
    {
      sources: [
        {
          source_id: CATALOGUE,
          kind: "backstage",
          name: "Catalogue",
          key: "billing",
          record_id: null,
        },
        { source_id: GONE, kind: "pagerduty", name: null, key: "PBILL01", record_id: null },
      ],
      attributes: { tier: { origin: "enrichment", rule: "criticality", confidence: 0.7 } },
    },
    1,
  ),
  entity(
    CHECKOUT,
    "Checkout",
    "service",
    1,
    {
      strategy: "hybrid",
      role: "reached",
      depth: 1,
      root: BILLING,
      via: DEPENDS,
      retrievers: [
        { retriever: "graph", rank: 1, score: 0.0909, detail: "1" },
        { retriever: "search", rank: 3, score: 0.0769, detail: "billing" },
      ],
    },
    {},
    0.62,
  ),
  tie(DEPENDS, [CHECKOUT, "Checkout"], [BILLING, "Billing API"], 2, {
    sources: [
      { source_id: CATALOGUE, kind: "backstage", name: "Catalogue", key: null, record_id: "s-1" },
    ],
    evidence: ["dependsOn"],
  }),
  entity(
    LEDGER,
    "Ledger DB",
    "database",
    3,
    {
      strategy: "hybrid",
      role: "found",
      depth: null,
      root: null,
      via: null,
      retrievers: [
        {
          retriever: "timeline",
          rank: 1,
          score: 0.0727,
          detail: "deployment 2026-10-03T11:30:00+00:00",
        },
      ],
    },
    {},
    0.18,
  ),
  tie(DEPLOYED, [BILLING, "Billing API"], [LEDGER, "Ledger DB"], 4, {
    origin: "inferred",
    rule: "deployed_together",
    confidence: 0.8,
    inferred_from: [BILLING, LEDGER],
  }),
];

const READ: ContextRead = {
  id: CONTEXT,
  title: "Billing API",
  purpose: "Pourquoi Billing API est lent ?",
  subject: { type: "entity", id: BILLING },
  request: {
    roots: [BILLING],
    query: null,
    depth: 1,
    relationships: [],
    environment: null,
    limit: 100,
    window_days: 14,
    until: null,
    retrievers: [],
    strategy: "hybrid",
  },
  status: "assembled",
  current_version: 2,
  created_by: null,
  created_at: NOW,
  updated_at: NOW,
  refreshed_at: NOW,
  archived_at: null,
};

function run(
  retriever: string,
  status: "ok" | "failed" | "timeout" | "skipped",
  found: number,
  error: string | null = null,
): AssembledContext["retrieval"][number] {
  return { retriever, version: 1, status, found, ms: 12, detail: null, error };
}

function assembled(version: number, over: Partial<AssembledContext> = {}): AssembledContext {
  return {
    contract_version: 1,
    context_id: CONTEXT,
    version,
    status: "assembled",
    error: null,
    title: READ.title,
    purpose: READ.purpose,
    subject: READ.subject,
    request: READ.request,
    strategy: { name: "neighbourhood", version: 1 },
    elements: ELEMENTS,
    sources: [{ source_id: CATALOGUE, kind: "backstage", name: "Catalogue", elements: 3 }],
    summary: {
      entities: 3,
      relationships: 2,
      stated: 1,
      inferred: 1,
      by_type: {},
      by_source_kind: {},
      by_retriever: { graph: 1, search: 2, timeline: 1 },
    },
    retrieval: [
      run("search", "ok", 2),
      run("content", "failed", 0, "ProgrammingError: the retriever failed."),
      run("graph", "ok", 1),
      run("timeline", "ok", 1),
      run("paths", "skipped", 0, "Fewer than two roots: no way between them to follow."),
    ],
    truncated: false,
    dropped: 0,
    model_built_at: NOW,
    model_version: 9,
    assembled_at: NOW,
    ...over,
  };
}

function version(n: number, over: Partial<ContextVersion> = {}): ContextVersion {
  return {
    version: n,
    status: "assembled",
    trigger: n === 1 ? "created" : "refreshed",
    reason: null,
    strategy: { name: "neighbourhood", version: 1 },
    contract_version: 1,
    request: READ.request,
    model_built_at: NOW,
    model_version: 9,
    element_count: 5,
    truncated: false,
    dropped: 0,
    summary: assembled(n).summary,
    retrieval: [],
    fingerprint: `f${n}`,
    error: null,
    assembled_at: NOW,
    assembled_by: null,
    ...over,
  };
}

const DIFF: ContextDiff = {
  context_id: CONTEXT,
  from_version: 1,
  to_version: 2,
  added: [ELEMENTS[3]],
  removed: [entity(GONE, "Payments", "team", 5, ELEMENTS[1].reason)],
  changed: [
    { before: ELEMENTS[0], after: ELEMENTS[0], fields: ["attributes.tier", "provenance.sources"] },
  ],
  unchanged: 3,
};

function show() {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>
        <EntityContext entityId={BILLING} entityName="Billing API" />
      </LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  permissions.value = ["intention:read", "intention:create"];
  api.ofEntity.mockResolvedValue([READ]);
  api.versions.mockResolvedValue([version(2), version(1)]);
  api.assembled.mockImplementation((_id: string, n?: number) =>
    Promise.resolve(assembled(n ?? 2)),
  );
  api.diff.mockResolvedValue(DIFF);
});

describe("the context tab", () => {
  it("says there is none yet, and assembles one around the entity", async () => {
    api.ofEntity.mockResolvedValueOnce([]);
    api.create.mockResolvedValue(assembled(1));
    const user = userEvent.setup();
    show();

    expect(await screen.findByText("Aucun contexte assemblé")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Pourquoi ?"), "Pourquoi Billing API est lent ?");
    await user.click(screen.getByRole("button", { name: "Assembler le contexte" }));

    expect(api.create).toHaveBeenCalledWith({
      title: "Billing API",
      purpose: "Pourquoi Billing API est lent ?",
      subject: { type: "entity", id: BILLING },
      roots: [BILLING],
      depth: 1,
      limit: 100,
      window_days: 14,
      strategy: "hybrid",
    }, expect.anything());
    expect(notify.success).toHaveBeenCalledWith({ title: "Contexte assemblé : 5 élément(s)." });
    expect(await screen.findByTestId("entity-context")).toBeInTheDocument();
  });

  it("says when the entity is not in the company model yet", async () => {
    api.ofEntity.mockResolvedValueOnce([]);
    api.create.mockRejectedValue(new ApiError(404, "/context", "Not in the model."));
    const user = userEvent.setup();
    show();

    await user.click(await screen.findByRole("button", { name: "Assembler le contexte" }));
    expect(notify.error).toHaveBeenCalledWith({
      title:
        "Cet élément n'est pas encore dans le modèle de l'entreprise : il y entrera à sa prochaine construction.",
    });
  });

  it("shows each element, why it is there, and where it came from", async () => {
    const user = userEvent.setup();
    show();

    const rows = await screen.findAllByTestId("context-element");
    expect(rows).toHaveLength(5);
    expect(screen.getByTestId("context-version-line")).toHaveTextContent("Version 2");
    expect(rows[0]).toHaveTextContent("Billing API");
    expect(rows[0]).toHaveTextContent("Point de départ");
    expect(rows[1]).toHaveTextContent("À 1 pas · par « dépend de »");
    expect(rows[2]).toHaveTextContent("Checkout dépend de Billing API");
    expect(rows[2]).toHaveTextContent("Lien entre deux éléments");

    await user.click(within(rows[0]).getByRole("button", { name: "Provenance de Billing API" }));
    const root = within(rows[0]).getByTestId("context-provenance");
    expect(root).toHaveTextContent("Catalogue (backstage) · clé billing");
    expect(root).toHaveTextContent("source supprimée depuis (pagerduty) · clé PBILL01");
    expect(root).toHaveTextContent("Règle criticality · 70 % : tier");
    expect(root).toHaveTextContent('service "Billing API"');

    await user.click(
      within(rows[4]).getByRole("button", { name: "Provenance de Billing API → Ledger DB" }),
    );
    const inferred = within(rows[4]).getByTestId("context-provenance");
    expect(inferred).toHaveTextContent(
      "Déduit par la règle deployed_together · 80 % de confiance",
    );
    expect(inferred).toHaveTextContent("Aucune : déduit par LEKA");
    expect(inferred).toHaveTextContent("Déduit à partir deBilling API, Ledger DB");

    await user.click(within(rows[2]).getByRole("button", { name: /Provenance de Checkout/ }));
    expect(within(rows[2]).getByTestId("context-provenance")).toHaveTextContent(
      "Catalogue (backstage) · enregistrement s-1",
    );
  });

  it("says how each was found, how relevant, and what each retriever did", async () => {
    const user = userEvent.setup();
    show();

    const rows = await screen.findAllByTestId("context-element");
    expect(rows[0]).toHaveTextContent("100 %");
    expect(rows[1]).toHaveTextContent("62 %");
    expect(rows[3]).toHaveTextContent("Trouvé par Chronologie");
    const report = screen.getByTestId("context-retrieval");
    expect(report).toHaveTextContent("Recherche · 2 trouvé(s)");
    expect(report).toHaveTextContent("Contenu · en échec");
    expect(report).toHaveTextContent("Chemins · sans objet");
    expect(within(report).getByText(/Contenu/)).toHaveAttribute(
      "title",
      "ProgrammingError: the retriever failed.",
    );

    await user.click(within(rows[1]).getByRole("button", { name: "Provenance de Checkout" }));
    const checkout = within(rows[1]).getByTestId("context-provenance");
    expect(checkout).toHaveTextContent("Graphe · rang 1 · à 1 pas");
    expect(checkout).toHaveTextContent("Recherche · rang 3 · mots : billing");
    expect(checkout).toHaveTextContent("Pertinence62 %");

    await user.click(within(rows[3]).getByRole("button", { name: "Provenance de Ledger DB" }));
    expect(within(rows[3]).getByTestId("context-provenance")).toHaveTextContent(
      /Chronologie · rang 1 · déploiement le 3 oct\. 2026/,
    );
  });

  it("keeps every version: shows one again, compares two", async () => {
    const user = userEvent.setup();
    show();

    const versions = await screen.findByTestId("context-versions");
    expect(within(versions).getAllByRole("listitem")).toHaveLength(2);
    await user.click(within(versions).getByRole("button", { name: "Comparer à la v1" }));
    const diff = await screen.findByTestId("context-diff");
    expect(api.diff).toHaveBeenCalledWith(CONTEXT, 1, 2);
    expect(diff).toHaveTextContent(
      "1 ajouté(s) · 1 retiré(s) · 1 modifié(s) · 3 inchangé(s)",
    );
    expect(diff).toHaveTextContent("+ Ledger DB");
    expect(diff).toHaveTextContent("− Payments");
    expect(diff).toHaveTextContent("~ Billing API (tier, sources)");

    await user.click(within(versions).getByRole("button", { name: /^v1/ }));
    expect(api.assembled).toHaveBeenLastCalledWith(CONTEXT, 1);
  });

  it("says whether reassembling changed anything", async () => {
    api.refresh.mockResolvedValue({ changed: false, version: version(2) });
    const user = userEvent.setup();
    show();

    await user.click(await screen.findByRole("button", { name: "Réassembler" }));
    expect(api.refresh).toHaveBeenCalledWith(CONTEXT, expect.anything());
    expect(notify.success).toHaveBeenCalledWith({
      title: "Rien n'a changé : la version 2 tient toujours.",
    });
  });

  it("archives, says so, and offers nothing more than reading", async () => {
    api.ofEntity
      .mockResolvedValueOnce([READ])
      .mockResolvedValue([{ ...READ, status: "archived", archived_at: NOW }]);
    api.archive.mockResolvedValue({ ...READ, status: "archived", archived_at: NOW });
    const user = userEvent.setup();
    show();

    await user.click(await screen.findByRole("button", { name: "Archiver" }));
    expect(api.archive).toHaveBeenCalledWith(CONTEXT, expect.anything());
    expect(notify.success).toHaveBeenCalledWith({
      title: "Contexte archivé : il reste lisible, mais n'est plus réassemblé.",
    });
    expect(await screen.findByTestId("context-archived")).toHaveTextContent(
      "toutes ses versions restent lisibles",
    );
    expect(screen.queryByRole("button", { name: "Réassembler" })).not.toBeInTheDocument();
    expect(screen.getAllByTestId("context-element")).toHaveLength(5);
  });

  it("says when archiving failed", async () => {
    api.archive.mockRejectedValue(new ApiError(500, "/context", "Down."));
    const user = userEvent.setup();
    show();

    await user.click(await screen.findByRole("button", { name: "Archiver" }));
    expect(notify.error).toHaveBeenCalledWith({
      title: "LEKA n'a pas pu archiver ce contexte. Réessayez.",
    });
  });

  it("says why a version failed", async () => {
    api.assembled.mockResolvedValue(
      assembled(3, { status: "failed", error: "A root is gone.", elements: [] }),
    );
    show();

    expect(await screen.findByText("Échec : A root is gone.")).toBeInTheDocument();
  });

  it("lets a role that may not assemble read, and offers it nothing else", async () => {
    permissions.value = ["intention:read"];
    show();

    expect(await screen.findAllByTestId("context-element")).toHaveLength(5);
    expect(screen.queryByRole("button", { name: "Réassembler" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Nouveau contexte" })).not.toBeInTheDocument();
  });
});
