import type { Analysis, EvidenceRef, Recommendation } from "@/lib/intelligence";

/**
 * What the intelligence gallery draws (LEKA-341): the demo's incident —
 * payment-api's latency after v2.8.4 — in every state an analysis can be
 * in. Development only: no screen a customer sees reads these.
 */

// Fixed: a date computed at load differs between the server's render and
// the browser's, and React will not patch the attribute up.
const OPENED = "2026-10-03T10:00:00Z";
const DEPLOYED_AT = "2026-10-03T09:00:00Z";

export const RECORD: EvidenceRef = {
  id: "record",
  label: "OPS-1841",
  kind: "record",
  source: { kind: "jira", name: "OPS board" },
  detail: "l'enregistrement de l'incident",
  at: OPENED,
  href: "https://acme.atlassian.net/browse/OPS-1841",
  facts: [{ label: "Clé", value: "OPS-1841" }],
};

export const DEPLOYED: EvidenceRef = {
  id: "deployed",
  label: "Déploiement · payment-api v2.8.4",
  kind: "event",
  detail: "sur payment-api",
  at: DEPLOYED_AT,
  href: "/environment",
};

export const INFERRED: EvidenceRef = {
  id: "inferred",
  label: "auth-service partage postgres-prod",
  kind: "inference",
  detail: "observé dans le trafic, documenté nulle part",
  facts: [{ label: "Règle", value: "observed_traffic" }],
};

export const RECOMMENDATIONS: Recommendation[] = [
  {
    id: "rollback",
    title: "Revenir à payment-api v2.8.3",
    rationale: "La latence a commencé avec la version 2.8.4 ; la précédente tenait la charge.",
    effect: "3 services concernés",
    risk: "medium",
    reversible: true,
    confidence: 0.82,
    evidence: [DEPLOYED, RECORD],
  },
  {
    id: "drop-table",
    title: "Purger la table des sessions",
    rationale: "Elle a triplé en une semaine.",
    effect: "Toutes les sessions fermées",
    risk: "high",
    reversible: false,
    confidence: 0.41,
    evidence: [],
  },
];

export const COMPLETE: Analysis = {
  status: "complete",
  missing: [],
  findings: [
    {
      id: "state",
      statement: "payment-api p99 latency above 2s : clos, sev2.",
      evidence: [RECORD],
    },
    { id: "lasted", statement: "Il a duré 4 h.", evidence: [RECORD] },
    { id: "affects", statement: "Il touche payment-api.", evidence: [RECORD] },
  ],
  causes: [
    {
      id: "deploy",
      label: "payment-api v2.8.4",
      kind: "Déploiement",
      href: "/environment",
      confidence: 0.83,
      basis: "stated",
      why: "Une source le déclare.",
      evidence: [DEPLOYED, RECORD],
    },
    {
      id: "shared-db",
      label: "auth-service",
      kind: "Service",
      confidence: 0.55,
      basis: "inferred",
      why: "Il partage la base de payment-api : LEKA le soupçonne.",
      evidence: [INFERRED],
    },
  ],
  impact: {
    areas: [
      { id: "affected", label: "Touché", items: [{ id: "p", label: "payment-api" }] },
      {
        id: "dependents",
        label: "Qui en dépend",
        items: [
          { id: "c", label: "checkout" },
          { id: "o", label: "orders" },
        ],
      },
      { id: "capabilities", label: "Capacités métier", items: [{ id: "i", label: "Invoicing" }] },
    ],
    risk: "medium",
    riskBasis: "d'après la gravité déclarée (sev2)",
  },
  recommendations: RECOMMENDATIONS,
  uncertainties: ["1 changement(s) juste avant lui, sans lien établi avec lui."],
  confidence: 0.83,
};

export const PARTIAL: Analysis = {
  ...COMPLETE,
  status: "partial",
  missing: ["ce qu'il touche"],
  impact: { areas: [], risk: "unknown", riskBasis: "aucune gravité n'est déclarée" },
  recommendations: [],
  uncertainties: [
    "On ne sait pas ce qu'il touche : aucune source ne le relie à un service.",
    "Sa gravité n'est pas dite : le risque ne peut pas être évalué.",
  ],
};

export const INCONCLUSIVE: Analysis = {
  status: "inconclusive",
  missing: ["ce qui l'a causé", "ce qu'il touche"],
  findings: [
    { id: "state", statement: "OPS-2001 : ni son état ni sa gravité ne sont dits.", evidence: [] },
  ],
  causes: [],
  impact: null,
  recommendations: [],
  uncertainties: ["Aucune source ne dit ce qui l'a causé, et rien ne le laisse soupçonner."],
  confidence: null,
};

const EMPTY: Omit<Analysis, "status"> = {
  missing: [],
  findings: [],
  causes: [],
  impact: null,
  recommendations: [],
  uncertainties: [],
  confidence: null,
};

export const FAILED: Analysis = { ...EMPTY, status: "failed" };
export const PENDING: Analysis = { ...EMPTY, status: "pending" };
