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
 * assemble reads, and is offered nothing it cannot do. Ranked (LEKA-372):
 * each element's score and, opened, why that rank — signal by signal, in
 * words; what was folded into it; what its sources disagree on, every side
 * with who says so; what was left out, counted by why and listed. Keeping
 * up (LEKA-374): up to date, or behind since when and on what — each change
 * in words — and updated on asking; whether it follows the model, switched;
 * widened and narrowed, saying what of its request changed, or why not;
 * why each version was made and how it differs; every time it was made
 * again, by LEKA or on asking, and what came of it. Its API (LEKA-376):
 * archiving it, or stopping it following the model, offered to its maker
 * or an admin only; LEKA making it again heard as it happens, and said.
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
  expand: vi.fn(),
  compress: vi.fn(),
  follow: vi.fn(),
  checks: vi.fn(),
  inspect: vi.fn(),
  evidence: vi.fn(),
  events: vi.fn(),
};
const permissions: { value: string[] } = { value: [] };
const notify = { success: vi.fn(), error: vi.fn(), info: vi.fn() };

vi.mock("@/lib/context", async (original) => ({
  ...(await original<typeof import("@/lib/context")>()),
  contexts: api,
}));
const me = { id: "7d3bc5ff-a12e-5e92-a5ae-ad6da2029a41" };
vi.mock("@/components/shell/shell-provider", () => ({
  usePermissions: () => permissions.value,
  useCurrentUser: () => me,
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
    min_relevance: 0.05,
  },
  status: "assembled",
  current_version: 2,
  // Made by who reads it: theirs to archive (LEKA-376).
  created_by: me.id,
  created_at: NOW,
  updated_at: NOW,
  refreshed_at: NOW,
  archived_at: null,
  follow: true,
  used_at: NOW,
  freshness: {
    state: "fresh",
    reasons: [],
    since: null,
    changes: 0,
    pending: [],
    checked_at: NOW,
    checked_model_at: NOW,
    following: "active",
  },
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
      accepted: 0,
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
    trigger: version === 1 ? "created" : "refreshed",
    change_count: 0,
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
    left_out: {},
    conflicts: 0,
    change_count: 0,
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
  api.checks.mockResolvedValue([]);
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
      min_relevance: 0.05,
    }, expect.anything());
    expect(notify.success).toHaveBeenCalledWith({ title: "Contexte assemblé : 5 éléments." });
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
    expect(inferred).toHaveTextContent("Déduit par la règle deployed_together · Confiance moyenne");
    expect(within(inferred).getByTestId("confidence")).toHaveTextContent("80 %");
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
    expect(report).toHaveTextContent("Recherche · 2 trouvés");
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
      "1 ajouté · 1 retiré · 1 modifié · 3 inchangés",
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

  it("says how each was ranked, what its sources disagree on, and what was left out", async () => {
    const ranked = (
      element: ContextElement,
      ranking: Partial<NonNullable<ContextElement["ranking"]>>,
    ): ContextElement => ({
      ...element,
      ranking: {
        score: 0.5,
        rank: null,
        topic: 0.5,
        trust: 0.9,
        signals: [],
        conflicts: [],
        duplicates: [],
        ...ranking,
      },
    });
    const signal = (
      name: string,
      axis: "topic" | "trust",
      value: number | null,
      detail: Record<string, unknown> = {},
    ) => ({ name, axis, value, weight: 0.25, detail, said: name });
    const tier = `attribute:${BILLING}:tier`;
    const [billing, checkout, ...rest] = ELEMENTS;
    api.assembled.mockResolvedValue(
      assembled(2, {
        elements: [
          ranked(billing, {
            score: 0.96,
            rank: 1,
            topic: 1,
            trust: 0.9,
            conflicts: [tier],
            signals: [
              signal("asked", "topic", 1),
              signal("confidence", "trust", 0.9),
              signal("freshness", "trust", 1, { days: 0 }),
              signal("sources", "trust", 1, {
                source: "Catalogue",
                status: "active",
                health: "healthy",
              }),
              signal("quality", "trust", null),
            ],
          }),
          ranked(checkout, {
            rank: 2,
            duplicates: [
              { ref_id: GONE, label: "checkout-web", rule: "same_name", confidence: 0.8 },
            ],
          }),
          ...rest,
        ],
        conflicts: [
          {
            id: tier,
            kind: "attribute",
            subject: BILLING,
            label: "Billing API",
            about: "tier",
            chosen: 1,
            values: [
              { value: 1, by: ["Catalogue"] },
              { value: 2, by: ["a deleted source"] },
            ],
            refs: [BILLING],
            said: "The sources of Billing API disagree on tier.",
          },
        ],
        ranking: {
          version: 1,
          min_relevance: 0.05,
          trust_share: 0.4,
          weights: {},
          left_out: { duplicate: 1, low_relevance: 1, budget: 0, ties: 2 },
          left: [
            {
              ref_id: GONE,
              ref_type: "service",
              label: "checkout-web",
              reason: "duplicate",
              score: 0.42,
              duplicate_of: CHECKOUT,
              said: "Probably the same as Checkout.",
            },
            {
              ref_id: DEPLOYED,
              ref_type: "service",
              label: "Noise",
              reason: "low_relevance",
              score: 0.03,
              said: "Scored 0.03, under 0.05.",
            },
          ],
        },
      }),
    );
    const user = userEvent.setup();
    show();

    const rows = await screen.findAllByTestId("context-element");
    expect(within(rows[0]).getByTestId("element-score")).toHaveTextContent("96 %");
    expect(within(rows[0]).getByTestId("element-disputed")).toHaveTextContent("Conflit");
    expect(rows[1]).toHaveTextContent("+1 doublon");
    expect(within(rows[1]).queryByTestId("element-disputed")).toBeNull();

    await user.click(within(rows[0]).getByRole("button", { name: "Provenance de Billing API" }));
    const why = within(rows[0]).getByTestId("element-ranking");
    expect(why).toHaveTextContent("N° 1 · score 96 %");
    expect(why).toHaveTextContent("Pertinence pour la demande · 100 %");
    expect(why).toHaveTextContent("Fiabilité · 90 %");
    const said = within(why)
      .getAllByTestId("ranking-signal")
      .map((line) => line.textContent);
    expect(said).toEqual([
      "Demandé100 %point de départ demandé",
      "Résolution90 %la résolution en est sûre à 90 %",
      "Fraîcheur100 %vu par une source aujourd'hui",
      "Sources100 %Catalogue : active, saine",
      "Qualité—jamais mesurée",
    ]);
    await user.click(within(rows[1]).getByRole("button", { name: "Provenance de Checkout" }));
    expect(rows[1]).toHaveTextContent("Doublons regroupéscheckout-web (same_name, 80 %)");

    const conflicts = screen.getByRole("region", { name: "Conflits (1)" });
    expect(conflicts).toHaveTextContent("Billing API · tier");
    expect(conflicts).toHaveTextContent("Les sources divergent");
    expect(conflicts).toHaveTextContent("1 (retenu) · selon Catalogue");
    expect(conflicts).toHaveTextContent("2 · selon une source supprimée depuis");

    const left = screen.getByRole("region", { name: "Laissés de côté (2)" });
    expect(left).toHaveTextContent("Seuil 5 % · la fiabilité pèse jusqu'à 40 % du score");
    expect(left).toHaveTextContent("Doublon1Peu pertinent1Au-delà du budget0");
    expect(left).toHaveTextContent("2 liens partis avec une extrémité");
    await user.click(within(left).getByRole("button", { name: "Voir la liste" }));
    expect(within(left).getByTestId("left-out-list")).toHaveTextContent(
      "checkout-web · Doublon · 42 % · doublon de Checkout",
    );

    // The figures say why, and what is disputed is said uncertain.
    expect(screen.getByTestId("context-used")).toHaveTextContent(
      "1 doublon · 1 peu pertinent · 0 au-delà du budget",
    );
    expect(screen.getByTestId("uncertainties")).toHaveTextContent(
      "Ses sources se contredisent sur 1 point : voir les conflits.",
    );
  });

  it("says it is behind the model, since when and on what, and updates it", async () => {
    api.ofEntity.mockResolvedValue([
      {
        ...READ,
        freshness: {
          ...READ.freshness,
          state: "stale",
          reasons: ["changes"],
          since: NOW,
          changes: 2,
          pending: [
            {
              kind: "entity",
              change: "removed",
              ref_id: CHECKOUT,
              type: "service",
              name: "Checkout",
              fields: ["lifecycle"],
              touches: "held",
            },
            {
              kind: "relationship",
              change: "removed",
              from_id: CHECKOUT,
              to_id: BILLING,
              type: "depends_on",
              name: "Checkout → Billing API",
              touches: "held",
            },
          ],
        },
      },
    ]);
    api.refresh.mockResolvedValue({ changed: true, version: version(3) });
    const user = userEvent.setup();
    show();

    const panel = await screen.findByTestId("context-freshness");
    expect(panel).toHaveAttribute("data-state", "stale");
    expect(panel).toHaveTextContent("Plus à jour : le modèle a changé");
    expect(panel).toHaveTextContent("2 changements du modèle touchent ce qu'il contient.");
    await user.click(within(panel).getByRole("button", { name: "Voir les changements (2)" }));
    const pending = within(screen.getByTestId("context-pending")).getAllByRole("listitem");
    expect(pending.map((item) => item.textContent)).toEqual([
      "Checkout dépend de Billing API — lien retiré",
      "Service Checkout — retiré (cycle de vie)",
    ]);

    await user.click(within(panel).getByRole("button", { name: "Mettre à jour" }));
    expect(api.refresh).toHaveBeenCalledWith(CONTEXT, expect.anything());
  });

  it("says whether it follows the model, and switches it", async () => {
    api.follow.mockResolvedValue({ ...READ, follow: false });
    const user = userEvent.setup();
    show();

    const panel = await screen.findByTestId("context-freshness");
    expect(panel).toHaveAttribute("data-state", "fresh");
    expect(panel).toHaveTextContent("À jour avec le modèle de l'entreprise");
    expect(screen.getByTestId("context-following")).toHaveTextContent(
      "Suit le modèle : LEKA le met à jour dès que ce qu'il contient change.",
    );
    await user.click(within(panel).getByRole("switch", { name: "Suivre le modèle" }));
    expect(api.follow).toHaveBeenCalledWith({ id: CONTEXT, follow: false }, expect.anything());
  });

  it("says when nobody used it for a while", async () => {
    api.ofEntity.mockResolvedValue([
      { ...READ, freshness: { ...READ.freshness, following: "dormant" } },
    ]);
    show();

    expect(await screen.findByTestId("context-following")).toHaveTextContent(
      "En veille : personne ne l'a utilisé depuis 14 jours.",
    );
  });

  it("widens and narrows, saying what of its request changed, or why not", async () => {
    api.expand.mockResolvedValue({
      changed: true,
      version: version(3, {
        trigger: "expanded",
        changes: [
          { kind: "request", change: "changed", field: "depth", before: 1, after: 2 },
          { kind: "request", change: "changed", field: "limit", before: 100, after: 200 },
        ],
        change_count: 2,
      }),
    });
    api.compress.mockRejectedValue(new ApiError(422, "/context", "As narrow as it goes."));
    const user = userEvent.setup();
    show();

    await user.click(await screen.findByRole("button", { name: "Élargir" }));
    expect(api.expand).toHaveBeenCalledWith({ id: CONTEXT }, expect.anything());
    expect(notify.success).toHaveBeenCalledWith({
      title: "Version 3 : contexte élargi (portée (pas) : 1 → 2, budget : 100 → 200).",
    });

    await user.click(screen.getByRole("button", { name: "Resserrer" }));
    expect(notify.error).toHaveBeenCalledWith({
      title: "Ce contexte est déjà aussi resserré que possible : il garde ses points de départ.",
    });
  });

  it("says why each version was made, and every time it was made again", async () => {
    api.versions.mockResolvedValue([
      version(2, {
        trigger: "changed",
        changes: [
          {
            kind: "entity",
            change: "removed",
            ref_id: CHECKOUT,
            type: "service",
            name: "Checkout",
          },
        ],
        change_count: 3,
        delta: { added: 1, removed: 2, changed: 0, unchanged: 3 },
      }),
      version(1),
    ]);
    api.checks.mockResolvedValue([
      {
        checked_at: NOW,
        trigger: "changed",
        checked_by: null,
        changes: [],
        change_count: 3,
        outcome: "version",
        version: 2,
        model_built_at: NOW,
      },
      {
        checked_at: NOW,
        trigger: "refreshed",
        checked_by: BILLING,
        changes: [],
        change_count: 0,
        outcome: "unchanged",
        version: 1,
        model_built_at: NOW,
      },
    ]);
    show();

    const [latest] = within(await screen.findByTestId("context-versions")).getAllByRole(
      "listitem",
    );
    expect(latest).toHaveTextContent(/v2 · mise à jour par LEKA/);
    expect(within(latest).getByTestId("context-version-why")).toHaveTextContent(
      "après 3 changements du modèle · +1 −2 ~0",
    );
    const checks = within(await screen.findByTestId("context-checks")).findAllByRole("listitem");
    const [followed, asked] = await checks;
    expect(followed).toHaveTextContent(/Le modèle a changé .* · par LEKA/);
    expect(followed).toHaveTextContent("version 2 créée · après 3 changements");
    expect(asked).toHaveTextContent("rien de changé : la version 1 tient");
    expect(asked).not.toHaveTextContent("par LEKA");
  });

  it("offers archiving and unfollowing to its maker or an admin only", async () => {
    api.ofEntity.mockResolvedValue([{ ...READ, created_by: "someone-else" }]);
    const { unmount } = show();

    expect(await screen.findByRole("button", { name: "Réassembler" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Archiver" })).not.toBeInTheDocument();
    expect(screen.queryByRole("switch", { name: "Suivre le modèle" })).not.toBeInTheDocument();
    unmount();

    permissions.value = ["intention:read", "intention:create", "context:manage"];
    show();
    expect(await screen.findByRole("button", { name: "Archiver" })).toBeVisible();
    expect(screen.getByRole("switch", { name: "Suivre le modèle" })).toBeVisible();
  });

  it("hears LEKA making it again, says so, and reads it again", async () => {
    const opened: { url: string; heard: Map<string, (event: MessageEvent) => void> }[] = [];
    class FakeEventSource {
      heard = new Map<string, (event: MessageEvent) => void>();
      constructor(url: string, init?: { withCredentials?: boolean }) {
        expect(init?.withCredentials).toBe(true);
        opened.push({ url, heard: this.heard });
      }
      addEventListener(name: string, listener: (event: MessageEvent) => void) {
        this.heard.set(name, listener);
      }
      close() {}
    }
    vi.stubGlobal("EventSource", FakeEventSource);
    api.events.mockReturnValue("http://api/context/events");
    show();
    await screen.findAllByTestId("context-element");
    const calls = api.assembled.mock.calls.length;

    const [stream] = opened;
    expect(stream.url).toBe("http://api/context/events");
    expect(api.events).toHaveBeenCalledWith(CONTEXT);
    stream.heard.get("check")?.(
      new MessageEvent("check", {
        data: JSON.stringify({
          version: 3,
          trigger: "changed",
          outcome: "version",
          checked_by: null,
        }),
      }),
    );
    expect(notify.info).toHaveBeenCalledWith({
      title: "LEKA a mis ce contexte à jour : version 3.",
    });
    await vi.waitFor(() => expect(api.assembled.mock.calls.length).toBeGreaterThan(calls));
    vi.unstubAllGlobals();
  });
});
