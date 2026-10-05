/**
 * How good a context is, as the screens say it (LEKA-375):
 * components/environment/context-quality.tsx.
 *
 * What these protect: the level, the score and why it was held down; what
 * it rests on, ticked when established — no critical disagreement is one;
 * each measure as a share, and, asked, each factor with the elements it was
 * read from — unknown said, never a number; what is missing, the critical
 * first, each in French from its kind and the element it names — an
 * intention's as LEKA-373 says it; the disagreements judged; what each
 * retrieval brought; what people said, and something missing reported; an
 * element said useful once, then not again; compact, the level and what it
 * rests on only.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AssembledContext, ContextQuality } from "@/lib/context";
import { LocaleProvider } from "@/lib/i18n/locale-provider";
import { makeQueryClient } from "@/lib/query";

const api = { quality: vi.fn(), feedback: vi.fn() };
const notify = { success: vi.fn(), error: vi.fn(), info: vi.fn() };

vi.mock("@/lib/context", async (original) => ({
  ...(await original<typeof import("@/lib/context")>()),
  contexts: api,
}));
vi.mock("@/lib/notify", () => ({ notify }));

const { ElementFeedback, QualityPanel } = await import(
  "@/components/environment/context-quality"
);

const CONTEXT = "5c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const PAYMENT = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const AUTH = "1c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";

const QUALITY: ContextQuality = {
  version: 1,
  score: 0.84,
  level: "medium",
  capped: "critical_conflict",
  measures: [
    {
      name: "completeness",
      score: 0.9333,
      weight: 0.35,
      factors: [
        { name: "start", value: 1, weight: 0.25, said: "x", refs: [PAYMENT], detail: {} },
        { name: "knowledge", value: null, weight: 0.2, said: "x", refs: [], detail: {} },
      ],
    },
    { name: "confidence", score: 0.7, weight: 0.4, factors: [] },
    { name: "freshness", score: null, weight: 0.25, factors: [] },
  ],
  gaps: [
    {
      kind: "no_owner",
      severity: "critical",
      measure: "completeness",
      origin: "quality",
      said: "Nobody is known to own payment-api.",
      refs: [PAYMENT],
      detail: { entity: "payment-api" },
    },
    {
      kind: "no_source_for",
      severity: "warning",
      measure: "completeness",
      origin: "intent",
      said: "None.",
      refs: [],
      detail: { needs: ["incidents"] },
    },
    {
      kind: "budget_cut",
      severity: "info",
      measure: "completeness",
      origin: "quality",
      said: "x",
      refs: [],
      detail: { count: 3, budget: 100 },
    },
  ],
  conflicts: [
    {
      id: "attribute:p:sla",
      kind: "attribute",
      subject: PAYMENT,
      label: "payment-api",
      about: "sla",
      severity: "critical",
      why: "x",
      said: "x",
      refs: [PAYMENT],
    },
  ],
  support: { entities: 4, sources: 3, events: 2, corroborated: 1, conflicts: 1, critical: 1 },
  retrieval: [
    { retriever: "graph", status: "ok", found: 5, kept: 3, only: 1, top: 3, said: "x" },
    { retriever: "content", status: "failed", found: 0, kept: 0, only: 0, top: 0, said: "x" },
  ],
  assessed: "assembled",
};

function assembled(over: Partial<AssembledContext> = {}): AssembledContext {
  return {
    contract_version: 1,
    context_id: CONTEXT,
    version: 2,
    status: "assembled",
    error: null,
    title: "payment-api",
    purpose: "Pourquoi payment-api est lent ?",
    subject: { type: "entity", id: PAYMENT },
    request: {
      roots: [PAYMENT],
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
    strategy: { name: "hybrid", version: 1 },
    elements: [
      {
        position: 0,
        kind: "entity",
        ref_id: PAYMENT,
        ref_type: "service",
        label: "payment-api",
        entity: null,
        relationship: null,
        provenance: {
          origin: "stated",
          rule: null,
          confidence: 1,
          sources: [],
          evidence: [],
          inferred_from: [],
          attributes: {},
          conflicts: [],
          first_seen_at: null,
          last_seen_at: null,
          changed_at: null,
        },
        reason: {
          strategy: "hybrid",
          role: "root",
          depth: 0,
          root: null,
          via: null,
          retrievers: [],
        },
        relevance: 1,
        text: "payment-api",
      },
    ],
    sources: [],
    summary: {
      entities: 1,
      relationships: 0,
      stated: 0,
      inferred: 0,
      by_type: {},
      by_source_kind: {},
      by_retriever: {},
    },
    retrieval: [],
    truncated: false,
    dropped: 0,
    model_built_at: null,
    model_version: 1,
    assembled_at: "2026-10-05T12:00:00Z",
    trigger: "created",
    change_count: 0,
    quality: QUALITY,
    ...over,
  } as AssembledContext;
}

function show(node: React.ReactNode) {
  return render(
    <QueryClientProvider client={makeQueryClient()}>
      <LocaleProvider>{node}</LocaleProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.quality.mockResolvedValue({
    context_id: CONTEXT,
    version: 2,
    quality: QUALITY,
    freshness: {},
    feedback: { useful: 2, not_useful: 0, wrong: 1, missing: 0 },
    given: [],
  });
  api.feedback.mockResolvedValue({ id: "f1" });
});

describe("the quality of a context", () => {
  it("says its level, why it was held down, and what it rests on", async () => {
    show(<QualityPanel assembled={assembled()} canMake />);

    const panel = screen.getByTestId("intelligence-confidence");
    expect(within(panel).getByRole("heading", { name: "Qualité du contexte" })).toBeVisible();
    expect(within(panel).getByTestId("confidence")).toHaveTextContent("Moyenne");
    expect(screen.getByTestId("quality-score")).toHaveTextContent(
      "Score : 84 % · plafonné : un désaccord critique",
    );
    const support = within(screen.getByTestId("support")).getAllByRole("listitem");
    expect(support.map((item) => [item.textContent, item.dataset.established])).toEqual([
      ["3 source(s) analysée(s)", "true"],
      ["2 événement(s) corrélé(s)", "true"],
      ["1 élément(s) sur 4 confirmé(s) par deux sources", "false"],
      ["1 contradiction(s) détectée(s), dont 1 critique(s)", "false"],
    ]);
    const measures = screen.getByTestId("quality-measures");
    expect(measures).toHaveTextContent("Complétude93 %");
    expect(measures).toHaveTextContent("Fiabilité70 %");
    expect(measures).toHaveTextContent("Fraîcheurinconnu");
  });

  it("says each factor, what it was read from, and an unknown as unknown", async () => {
    const user = userEvent.setup();
    show(<QualityPanel assembled={assembled()} />);

    await user.click(screen.getByRole("button", { name: "Voir le détail des mesures" }));
    const factors = screen.getAllByTestId("quality-factors")[0];
    expect(within(factors).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Points de départ · 100 % · lu sur payment-api",
      "Connu du modèle · inconnu",
    ]);
    expect(screen.getByTestId("quality-retrieval")).toHaveTextContent(
      "Graphe5 trouvé(s) · 3 gardé(s) · 1 seule · 3 en tête",
    );
  });

  it("says what is missing in French, the critical first, and the disagreements judged", () => {
    show(<QualityPanel assembled={assembled()} />);

    const gaps = within(screen.getByTestId("quality-gaps")).getAllByTestId("quality-gap");
    expect(gaps.map((gap) => gap.textContent)).toEqual([
      "CritiquePersonne n'est connu comme responsable de payment-api.",
      "À noterAucune source lue ne sait lire ce dont parle la demande : incidents.",
      "Pour info3 élément(s) pertinent(s) laissé(s) de côté par son budget de 100 : élargissez-le.",
    ]);
    const [conflict] = within(screen.getByTestId("quality-conflicts")).getAllByTestId(
      "quality-conflict",
    );
    expect(conflict).toHaveAttribute("data-severity", "critical");
    expect(conflict).toHaveTextContent("Critiquepayment-api · sla");
    expect(conflict).toHaveTextContent("sur ce qui décide d'une réponse");
  });

  it("says what people said, and reports what is missing", async () => {
    const user = userEvent.setup();
    show(<QualityPanel assembled={assembled()} canMake />);

    expect(
      await screen.findByText("2 utile(s) · 0 pas utile(s) · 1 faux · 0 manque(s)"),
    ).toHaveAttribute("data-testid", "quality-feedback-counts");
    expect(api.quality).toHaveBeenCalledWith(CONTEXT, 2);
    await user.type(screen.getByLabelText("Il manque quelque chose ?"), "Le runbook de paiement");
    await user.click(screen.getByRole("button", { name: "Signaler" }));
    expect(api.feedback).toHaveBeenCalledWith(
      {
        id: CONTEXT,
        body: { version: 2, verdict: "missing", note: "Le runbook de paiement" },
      },
      expect.anything(),
    );
    expect(notify.success).toHaveBeenCalledWith({ title: "Merci : votre retour est noté." });
  });

  it("says, compact, the level and what it rests on only", () => {
    show(<QualityPanel assembled={assembled()} compact title="Niveau de confiance" />);

    expect(screen.getByRole("heading", { name: "Niveau de confiance" })).toBeVisible();
    expect(screen.getByTestId("support")).toBeVisible();
    expect(screen.queryByTestId("quality-gaps")).not.toBeInTheDocument();
    expect(screen.queryByTestId("quality-feedback")).not.toBeInTheDocument();
    expect(api.quality).not.toHaveBeenCalled();
  });

  it("is not drawn when nothing judged it", () => {
    show(<QualityPanel assembled={assembled({ quality: null })} />);
    expect(screen.queryByTestId("context-quality")).not.toBeInTheDocument();
  });
});

describe("an element, said useful", () => {
  it("says it once, then not again", async () => {
    const user = userEvent.setup();
    show(<ElementFeedback contextId={CONTEXT} version={2} refId={AUTH} />);

    const asked = screen.getByRole("group", { name: "Cet élément vous sert-il ?" });
    await user.click(within(asked).getByRole("button", { name: "Faux" }));
    expect(api.feedback).toHaveBeenCalledWith(
      { id: CONTEXT, body: { version: 2, ref_id: AUTH, verdict: "wrong" } },
      expect.anything(),
    );
    expect(within(asked).getByRole("button", { name: "Faux" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    for (const button of within(asked).getAllByRole("button")) expect(button).toBeDisabled();
  });
});
