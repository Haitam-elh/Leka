/**
 * An intention's analysis, read as the screens show an analysis (LEKA-388).
 *
 * What these protect: each sentence worded from its code and values, in
 * the interface's language — the API's own for a code it does not know;
 * a tie's evidence worded from its ends; each finding titled by the
 * capability that said it, its evidence opened from it — where it came
 * from, its record, who cites it; a cause kept a hypothesis, its why
 * worded; what it reaches by area, with the risk and its basis; what is
 * missing, unknown, and what the confidence rests on; no proposal; an
 * analysis not run is not drawn as one.
 */

import { describe, expect, it } from "vitest";

import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import {
  analysisEvidence,
  evidenceRef,
  type IntentionAnalysis,
  intentionAnalysis,
  type Links,
  noteSaid,
} from "@/lib/intention-analysis";

const fr = DICTIONARIES.fr;
const en = DICTIONARIES.en;
const BILLING = "0c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const PAYMENTS = "1c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const CHECKOUT = "2c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const DEPLOY = "3c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";
const CATALOGUE = "4c3bc5ff-a12e-5e92-a5ae-ad6da2029a41";

const links: Links = {
  href: ({ id, type }) => `/environment/${type}/${id}`,
  typeName: (type) =>
    ({ service: "Service", team: "Équipe", deployment: "Déploiement" })[type] ?? type,
  date: (iso) => iso.slice(0, 10),
};

type Step = IntentionAnalysis["steps"][number];

function step(name: string, status: Step["status"], ms: number): Step {
  return {
    name,
    version: 1,
    status,
    duration_ms: ms,
    error: null,
    reason: null,
    level: 0,
    started_ms: 0,
    handed: [],
    degraded: [],
    fallback_of: null,
  };
}

function analysisFixture(overrides: Partial<IntentionAnalysis> = {}): IntentionAnalysis {
  return {
    id: "a1",
    intention_id: "i1",
    number: 1,
    trigger: "created",
    status: "partial",
    requested_by: null,
    context_id: "c1",
    context_version: 2,
    readiness: "ready",
    started_at: "2026-10-08T09:00:00Z",
    finished_at: "2026-10-08T09:00:01.200Z",
    selection: [
      { name: "standing", version: 1, method: "rules", chosen: true, reason: "always" },
      { name: "ownership", version: 1, method: "rules", chosen: true, reason: "goal" },
      { name: "changes", version: 1, method: "rules", chosen: true, reason: "kind" },
      { name: "migration", version: 1, method: "rules", chosen: false, reason: "not_called" },
    ],
    steps: [
      step("standing", "succeeded", 12),
      step("ownership", "succeeded", 30),
      { ...step("changes", "timed_out", 15000), error: "TimeoutError" },
    ],
    result: {
      status: "partial",
      summary: [
        {
          code: "ownership.summary",
          text: "Billing API is owned by Payments.",
          params: { name: "Billing API", owners: ["Payments"] },
        },
      ],
      findings: [
        {
          id: `standing:${BILLING}`,
          capability: "standing",
          code: "standing.state",
          text: "Billing API (service) is active, criticality high.",
          params: {
            name: "Billing API",
            type: "service",
            lifecycle: "active",
            status: null,
            criticality: "high",
          },
          evidence: [`entity:${BILLING}`],
        },
        {
          id: `owner:${BILLING}`,
          capability: "ownership",
          code: "ownership.owner",
          text: "Billing API is owned by Payments.",
          params: { name: "Billing API", owners: ["Payments"], count: 1 },
          evidence: [`tie:${BILLING}:owned_by:${PAYMENTS}`],
        },
        {
          id: "future",
          capability: "ownership",
          code: "ownership.something_new",
          text: "A sentence the interface does not know yet.",
          params: {},
          evidence: [],
        },
      ],
      causes: [
        {
          id: `cause:${DEPLOY}`,
          capability: "incidents",
          code: "cause.changed_before",
          label: "billing-api v2.8.4",
          basis: "inferred",
          why: "billing-api v2.8.4 changed 2.5 hour(s) before p99 opened, on what it affects.",
          confidence: 0.7,
          ref_type: "deployment",
          ref_id: DEPLOY,
          params: { incident: "p99 above 2s", hours: 2.5, kind: "deployment" },
          evidence: [`event:${DEPLOY}`],
        },
      ],
      impact: [
        {
          code: "dependents",
          items: [{ ref_type: "service", ref_id: CHECKOUT, name: "Checkout" }],
        },
      ],
      risk: "high",
      risk_basis: {
        code: "dependency.risk",
        text: "1 thing(s) rely on it, some critical.",
        params: { relying: 1, critical: true, business: 0 },
      },
      uncertainties: [
        {
          code: "ownership.several",
          text: "Several owners are named for Billing API: which one decides is not said.",
          params: { name: "Billing API", owners: ["Payments", "Platform"] },
        },
      ],
      missing: [
        {
          code: "capability.timed_out",
          text: "changes did not finish: timed out.",
          params: { capability: "changes", error: "TimeoutError" },
        },
      ],
      confidence: 0.9,
      support: [
        {
          code: "support.sources",
          text: "2 source(s) behind its context.",
          params: { count: 2, established: true },
        },
        {
          code: "support.contradictions",
          text: "1 contradiction(s) between them.",
          params: { count: 1, established: false },
        },
        {
          code: "support.context",
          text: "Its context is ready, its quality high.",
          params: { readiness: "ready", level: "high", established: true },
        },
      ],
      evidence: [
        {
          id: `entity:${BILLING}`,
          kind: "entity",
          label: "Billing API",
          ref_type: "service",
          ref_id: BILLING,
          sources: [{ id: CATALOGUE, kind: "backstage", name: "Catalogue" }],
          records: [],
          origin: "stated",
          confidence: 1,
          detail: "Billing API — service",
          at: null,
          params: {},
        },
        {
          id: `tie:${BILLING}:owned_by:${PAYMENTS}`,
          kind: "record",
          label: "Billing API owned by Payments",
          ref_type: "owned_by",
          ref_id: null,
          sources: [
            { id: CATALOGUE, kind: "backstage", name: "Catalogue" },
            { id: null, kind: null, name: null },
          ],
          records: ["component:billing-api"],
          origin: "stated",
          confidence: 0.95,
          detail: null,
          at: "2026-10-07T12:00:00Z",
          params: { from: "Billing API", to: "Payments" },
        },
        {
          id: `event:${DEPLOY}`,
          kind: "event",
          label: "billing-api v2.8.4",
          ref_type: "deployment",
          ref_id: DEPLOY,
          sources: [],
          records: [],
          origin: null,
          confidence: null,
          detail: "deployment",
          at: "2026-10-08T06:30:00Z",
          params: {},
        },
      ],
    },
    error: null,
    detail: {},
    ...overrides,
  };
}

describe("an intention's analysis", () => {
  it("words each sentence from its code — the API's own for one it does not know", () => {
    const analysis = intentionAnalysis(fr, analysisFixture(), links);
    expect(analysis.summary).toBe("Billing API appartient à Payments.");
    expect(analysis.findings.map((f) => [f.title, f.statement])).toEqual([
      ["État", "Billing API (Service) est actif, criticité high."],
      ["Responsabilités", "Billing API appartient à Payments."],
      ["Responsabilités", "A sentence the interface does not know yet."],
    ]);
    expect(intentionAnalysis(en, analysisFixture(), links).summary).toBe(
      "Billing API is owned by Payments.",
    );
    const restart = { code: "action.asked", text: "…", params: { action: "restart", on: ["Billing API"] } };
    expect(noteSaid(fr, restart, links)).toBe(
      "Demandé : Redémarrer Billing API. Une personne doit l'approuver avant toute exécution.",
    );
    expect(noteSaid(en, restart, links)).toBe(
      "Asked: Restart Billing API. A person must approve it before anything runs.",
    );
    expect(
      noteSaid(fr, { code: "migration.summary", text: "…", params: { target: null } }, links),
    ).toBe("La destination manque.");
    expect(
      noteSaid(
        fr,
        {
          code: "change.made",
          text: "…",
          params: {
            kind: "deployment",
            name: "v2.8.4",
            at: "2026-10-08T06:30:00Z",
            environment: "production",
            reached: 3,
            incidents: 1,
          },
        },
        links,
      ),
    ).toBe(
      "Déploiement v2.8.4 le 2026-10-08 en production : touche 3 élément(s), suivi de 1 incident(s).",
    );
  });

  it("opens each finding's evidence: where it came from, its record, who cites it", () => {
    const analysis = intentionAnalysis(fr, analysisFixture(), links);
    const [standing, owner] = analysis.findings;
    expect(standing.evidence[0]).toMatchObject({
      label: "Billing API",
      kind: "entity",
      source: { kind: "backstage", name: "Catalogue" },
      detail: "Service",
      href: `/environment/service/${BILLING}`,
    });
    const [tie] = owner.evidence;
    // A tie, worded from its ends: never the API's English.
    expect(tie.label).toBe("Billing API appartient à Payments");
    expect(tie.href).toBeNull();
    expect(tie.facts).toEqual([
      { label: "Origine", value: "dit par une source" },
      { label: "Confiance", value: "95 %" },
      { label: "Enregistrement(s)", value: "component:billing-api" },
      { label: "Aussi dit par", value: "une source supprimée depuis" },
      { label: "Cité par", value: "Responsabilités" },
    ]);
  });

  it("says what LEKA already concluded as Insights says it", () => {
    const concluded = {
      id: "finding:f1",
      kind: "inference" as const,
      label: "No team or person is named as owner of postgres-prod.",
      ref_type: "finding",
      ref_id: "f1",
      sources: [],
      records: [],
      origin: "leka",
      confidence: null,
      detail: "organisation · high",
      at: null,
      params: { code: "ownership.no_owner", params: { name: "postgres-prod", dependents: 3 } },
    };
    const worded = evidenceRef(fr, concluded, {
      ...links,
      finding: (code, params) => ({ title: `${code}: ${String(params.name)}`, detail: "worded" }),
    });
    expect([worded.label, worded.detail]).toEqual(["ownership.no_owner: postgres-prod", "worded"]);
    // Without its words, its own statement.
    expect(evidenceRef(fr, concluded, links).label).toBe(concluded.label);
  });

  it("keeps a cause a hypothesis, its why worded", () => {
    const [cause] = intentionAnalysis(fr, analysisFixture(), links).causes;
    expect(cause).toMatchObject({
      label: "billing-api v2.8.4",
      kind: "Déploiement",
      basis: "inferred",
      confidence: 0.7,
      href: `/environment/deployment/${DEPLOY}`,
      why: "Modifié 2.5 h avant l'ouverture de p99 above 2s, sur ce qu'il touche.",
    });
    expect(cause.evidence[0]).toMatchObject({ kind: "event", detail: "Déploiement · déploiement" });
  });

  it("says what it reaches, the risk and on what; what is missing, unknown, and sure", () => {
    const analysis = intentionAnalysis(fr, analysisFixture(), links);
    expect(analysis.status).toBe("partial");
    expect(analysis.impact).toEqual({
      areas: [
        {
          id: "dependents",
          label: "Ce qui en dépend",
          items: [
            {
              id: CHECKOUT,
              label: "Checkout",
              href: `/environment/service/${CHECKOUT}`,
              type: "service",
              detail: "Service",
            },
          ],
        },
      ],
      risk: "high",
      riskBasis: "1 élément(s) en dépendent, dont des éléments critiques.",
    });
    expect(analysis.missing).toEqual(["Changements n'a pas abouti : délai dépassé."]);
    expect(analysis.uncertainties).toEqual([
      "Plusieurs responsables sont nommés pour Billing API (Payments, Platform) : qui décide n'est pas dit.",
    ]);
    expect(analysis.support).toEqual([
      { id: "support.sources", label: "2 source(s) derrière son contexte", established: true },
      { id: "support.contradictions", label: "1 contradiction(s) entre elles", established: false },
      { id: "support.context", label: "Contexte prêt, qualité élevée", established: true },
    ]);
    expect(analysis.confidence).toBe(0.9);
    // Proposals are LEKA-389's: none here.
    expect(analysis.recommendations).toEqual([]);
  });

  it("lists every piece of evidence collected, in order, each with who cites it", () => {
    const items = analysisEvidence(fr, analysisFixture().result!, links);
    expect(items.map((item) => item.label)).toEqual([
      "Billing API",
      "Billing API appartient à Payments",
      "billing-api v2.8.4",
    ]);
    expect(items[2].facts).toEqual([{ label: "Cité par", value: "Incidents" }]);
  });

  it("draws an analysis not run, or on its way, as nothing found yet", () => {
    const blocked = intentionAnalysis(
      fr,
      analysisFixture({ status: "blocked", result: null, steps: [], selection: [] }),
      links,
    );
    expect(blocked.status).toBe("pending");
    expect(blocked.findings).toEqual([]);
    const running = analysisFixture({ status: "running", result: null });
    expect(intentionAnalysis(fr, running, links).status).toBe("running");
  });
});
