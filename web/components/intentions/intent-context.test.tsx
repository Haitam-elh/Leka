/**
 * Step 2 of a new intention (LEKA-373): the context it asks for.
 *
 * What these protect: the question, and a way back to change it; what is
 * missing, the critical first, each in words — what was tried, what
 * cannot be read; what LEKA understood — the kind and the words that said
 * it, what it is about and how it knows, when and from what, where, from
 * which sources; what it gathered, by kind of thing, and every element on
 * asking; the sources it came from; nothing is missing, said too. Asked
 * again (LEKA-374): which version, what LEKA reads differently, and how
 * what it gathered changed. Judged (LEKA-375): how sure LEKA can be, as
 * mockup 03's « Niveau de confiance », and what is missing — the context's
 * own gaps beside the intention's, the critical first.
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { IntentContext } from "@/components/intentions/intent-context";
import type { AssembledContext, ContextElement, IntentPlan } from "@/lib/context";
import { LocaleProvider } from "@/lib/i18n/locale-provider";

const PAYMENT = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const INCIDENT = "1c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const GITHUB = "2c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";

function entity(id: string, name: string, type: string): ContextElement {
  return {
    position: 0,
    kind: "entity",
    ref_id: id,
    ref_type: type,
    label: name,
    entity: {
      type,
      key: `${type}:${name}`,
      name,
      attributes: {},
      lifecycle: "active",
      version: 1,
      confidence: 1,
      quality: null,
    },
    relationship: null,
    provenance: {
      origin: "stated",
      rule: null,
      confidence: 1,
      sources: [{ source_id: GITHUB, kind: "github", name: "acme/backend", key: name, record_id: null }],
      evidence: [],
      inferred_from: [],
      attributes: {},
      conflicts: [],
      first_seen_at: null,
      last_seen_at: null,
      changed_at: null,
    },
    reason: { strategy: "hybrid", role: "root", depth: 0, root: null, via: null, retrievers: [] },
    relevance: 1,
    text: name,
  };
}

const PLAN: IntentPlan = {
  version: 1,
  text: "Pourquoi l'API de paiement est-elle plus lente depuis hier ?",
  intention_id: null,
  kind: "diagnose",
  kind_said: ["pourquoi", "lente"],
  facets: ["technical", "temporal", "organizational"],
  subjects: [
    {
      entity_id: PAYMENT,
      name: "payment-api",
      type: "service",
      facet: "technical",
      how: "named",
      said: "payment api",
      confidence: 0.8,
    },
  ],
  period: {
    since: "2026-10-06T00:00:00Z",
    until: "2026-10-07T15:30:00Z",
    origin: "text",
    said: "hier",
  },
  environment: "production",
  constraints: [],
  request: {
    roots: [PAYMENT],
    query: "x",
    depth: 2,
    relationships: [],
    environment: "production",
    limit: 100,
    window_days: 2,
    until: null,
    retrievers: [],
    strategy: "hybrid",
    min_relevance: 0.05,
  },
  gaps: [
    {
      kind: "nothing_happened",
      severity: "warning",
      said: "Nothing happened.",
      detail: {},
    },
    {
      kind: "no_source_for",
      severity: "critical",
      said: "None.",
      detail: { needs: ["incidents", "metrics"] },
    },
  ],
};

function assembled(over: Partial<AssembledContext> = {}): AssembledContext {
  return {
    contract_version: 1,
    context_id: "c1",
    version: 1,
    status: "assembled",
    error: null,
    title: PLAN.text,
    purpose: PLAN.text,
    subject: { type: "request", id: null },
    request: PLAN.request,
    strategy: { name: "hybrid", version: 1 },
    elements: [
      entity(PAYMENT, "payment-api", "service"),
      entity(INCIDENT, "payment-api p99 latency above 2s", "incident"),
    ],
    sources: [{ source_id: GITHUB, kind: "github", name: "acme/backend", elements: 2 }],
    summary: {
      entities: 2,
      relationships: 0,
      stated: 0,
      inferred: 0,
      accepted: 0,
      by_type: {},
      by_source_kind: {},
      by_retriever: {},
    },
    retrieval: [],
    truncated: false,
    dropped: 0,
    model_built_at: null,
    model_version: 1,
    assembled_at: "2026-10-07T15:30:00Z",
    intent: PLAN,
    trigger: "created",
    change_count: 0,
    ...over,
  };
}

function show(made: AssembledContext, onEdit = vi.fn()) {
  render(
    <LocaleProvider>
      <IntentContext assembled={made} onEdit={onEdit} />
    </LocaleProvider>,
  );
  return onEdit;
}

describe("the context an intention asks for", () => {
  it("says the question, what is missing first, and what LEKA understood", async () => {
    const user = userEvent.setup();
    const onEdit = show(assembled());

    expect(screen.getByTestId("intention-step-2")).toHaveTextContent(PLAN.text);
    await user.click(screen.getByRole("button", { name: "Modifier" }));
    expect(onEdit).toHaveBeenCalledOnce();

    const gaps = screen.getAllByTestId("intent-gap");
    expect(gaps.map((g) => g.dataset.kind)).toEqual(["no_source_for", "nothing_happened"]);
    expect(gaps[0]).toHaveTextContent(
      "CritiqueAucune source lue ne sait lire ce dont parle la demande : incidents, métriques.",
    );
    expect(gaps[1]).toHaveTextContent("À noter");

    const scope = screen.getByTestId("intent-scope");
    expect(scope).toHaveTextContent("Diagnostic · « pourquoi, lente »");
    expect(within(scope).getByRole("link", { name: /payment-api/ })).toHaveTextContent(
      "payment-api« payment api »",
    );
    expect(scope).toHaveTextContent("lue dans la demande : « hier »");
    expect(scope).toHaveTextContent("production");
    expect(scope).toHaveTextContent("Toutes les sources connectées");
  });

  it("shows what it gathered by kind, every element on asking, and where from", async () => {
    const user = userEvent.setup();
    show(assembled());

    const gathered = screen.getByTestId("intent-gathered");
    expect(gathered).toHaveTextContent("Service · 1");
    expect(gathered).toHaveTextContent("Incident · 1");
    await user.click(screen.getByRole("button", { name: "Voir tous les éléments" }));
    expect(
      within(screen.getByTestId("intent-elements")).getByRole("link", {
        name: "payment-api p99 latency above 2s",
      }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("intent-sources")).toHaveTextContent("acme/backend2 élément(s)");
  });

  it("says when nothing is missing, and names nothing when nothing was named", () => {
    show(
      assembled({
        intent: { ...PLAN, gaps: [], subjects: [], kind: "knowledge", kind_said: ["procedure"] },
      }),
    );
    expect(screen.getByTestId("intent-nothing-missing")).toHaveTextContent(
      "Rien ne manque pour lire cette demande.",
    );
    expect(screen.getByTestId("intent-scope")).toHaveTextContent("Aucun élément du modèle nommé");
  });

  it("says, asked again, which version it is and what LEKA reads differently", () => {
    show(
      assembled({
        version: 2,
        trigger: "reasked",
        changes: [
          {
            kind: "intent",
            change: "changed",
            field: "text",
            before: "Pourquoi ?",
            after: PLAN.text,
          },
          {
            kind: "intent",
            change: "changed",
            field: "kind",
            before: "ownership",
            after: "diagnose",
          },
          { kind: "request", change: "changed", field: "depth", before: 1, after: 2 },
        ],
        change_count: 3,
        delta: { added: 2, removed: 1, changed: 0, unchanged: 5 },
      }),
    );

    const again = screen.getByTestId("intent-asked-again");
    expect(again).toHaveTextContent(
      "Version 2 de ce contexte : votre demande a changé, LEKA l'a relue.",
    );
    expect(within(again).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "nature : Responsabilité → Diagnostic",
    ]);
    expect(again).toHaveTextContent(
      "Contexte : 2 élément(s) ajouté(s), 1 retiré(s), 0 modifié(s).",
    );
  });

  it("says how sure LEKA can be, and what is missing beside the intention's gaps", () => {
    show(
      assembled({
        quality: {
          version: 1,
          score: 0.59,
          level: "low",
          capped: "critical_gap",
          measures: [
            { name: "completeness", score: 0.8, weight: 0.35, factors: [] },
            { name: "confidence", score: 0.9, weight: 0.4, factors: [] },
            { name: "freshness", score: 1, weight: 0.25, factors: [] },
          ],
          gaps: [
            {
              kind: "no_owner",
              severity: "critical",
              measure: "completeness",
              origin: "quality",
              said: "x",
              refs: [PAYMENT],
              detail: { entity: "payment-api" },
            },
            {
              kind: "nothing_happened",
              severity: "warning",
              measure: "completeness",
              origin: "intent",
              said: "x",
              refs: [],
              detail: {},
            },
            {
              kind: "undocumented",
              severity: "info",
              measure: "completeness",
              origin: "quality",
              said: "x",
              refs: [PAYMENT],
              detail: { entity: "payment-api" },
            },
          ],
          conflicts: [],
          support: {
            entities: 2,
            sources: 1,
            events: 1,
            corroborated: 0,
            conflicts: 0,
            critical: 0,
          },
          retrieval: [],
          assessed: "assembled",
        },
      }),
    );

    const sure = screen.getByTestId("intelligence-confidence");
    expect(within(sure).getByRole("heading", { name: "Niveau de confiance" })).toBeVisible();
    expect(within(sure).getByTestId("confidence")).toHaveTextContent("Faible");
    expect(within(sure).getByTestId("support")).toHaveTextContent("1 source(s) analysée(s)");
    expect(within(sure).getByTestId("support")).toHaveTextContent(
      "0 contradiction(s) détectée(s)",
    );
    expect(screen.getAllByTestId("intent-gap").map((gap) => gap.textContent)).toEqual([
      "CritiquePersonne n'est connu comme responsable de payment-api.",
      "À noterRien ne s'est passé sur la période autour de ce dont parle la demande.",
      "Pour infoAucune page ne décrit payment-api.",
    ]);
  });
});
