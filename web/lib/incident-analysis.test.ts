/**
 * An incident read as an analysis (LEKA-341): lib/incident-analysis.ts.
 *
 * What these protect: what its sources say becomes findings with their
 * evidence — its records, its timeline, what it touches and why; what is
 * said or suspected to have caused it becomes probable causes, the surest
 * first, a source's word told apart from LEKA's inference, with what
 * changed just before it as evidence; the risk read from its severity, or
 * unknown; what is only suspected or not known said as such; complete,
 * partial — saying what is missing — or inconclusive; no recommendation
 * made up.
 */

import { describe, expect, it } from "vitest";

import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import { incidentAnalysis } from "@/lib/incident-analysis";
import type { IncidentDetail } from "@/lib/incidents";

const t = DICTIONARIES.fr;
const links = {
  href: (entity: { id: string; type: string }) => `/environment/${entity.type}s/${entity.id}`,
  typeName: (type: string) => ({ deployment: "Déploiement", change: "Changement" })[type] ?? type,
  source: (id: string) => (id === "s1" ? { kind: "jira", name: "OPS board" } : null),
};

type Brief = IncidentDetail["affects"][number];
const brief = (id: string, name: string, type: string): Brief => ({
  id,
  type: type as Brief["type"],
  key: `${type}:${id}`,
  name,
  lifecycle: "active",
});
const SERVICE = brief("svc", "payment-api", "service");
const DEPLOY = brief("dep", "payment-api v2.8.4", "deployment");
const FLAG = brief("flag", "Feature flag flipped", "change");
const OTHER = brief("other", "auth-service v1.2", "deployment");

function incident(over: Partial<IncidentDetail> = {}): IncidentDetail {
  return {
    id: "inc",
    key: "OPS-1841",
    name: "payment-api p99 latency above 2s",
    lifecycle: "active",
    url: "https://acme.atlassian.net/browse/OPS-1841",
    tools: ["jira"],
    state: "closed",
    priority: null,
    severity: "sev2",
    urgency: null,
    opened_at: "2026-10-03T10:00:00Z",
    acknowledged_at: null,
    resolved_at: "2026-10-03T14:00:00Z",
    time_to_acknowledge_minutes: null,
    duration_minutes: 240,
    affects: [SERVICE],
    commander: null,
    assignees: [],
    causes: [DEPLOY],
    attributes: {},
    provenance: { sources: [{ source_id: "s1", key: "OPS-1841", kind: "key" }] },
    timeline: [
      { at: "2026-10-03T10:00:00Z", step: "opened", state: null, origin: "source" },
      { at: "2026-10-03T14:00:00Z", step: "resolved", state: null, origin: "source" },
    ],
    affected: [{ entity: SERVICE, origin: "stated", rule: "stated", confidence: 1 }],
    people: [],
    suspected_causes: [
      { entity: FLAG, origin: "inferred", rule: "preceded", confidence: 0.6 },
      { entity: DEPLOY, origin: "stated", rule: "stated", confidence: 0.83 },
    ],
    changed_before: [
      {
        entity: DEPLOY,
        kind: "deployment",
        at: "2026-10-03T09:00:00Z",
        state: "succeeded",
        environment: "production",
        via: SERVICE,
      },
      {
        entity: OTHER,
        kind: "deployment",
        at: "2026-10-03T08:00:00Z",
        state: "succeeded",
        environment: "production",
        via: null,
      },
    ],
    impact: {
      affected: [SERVICE],
      dependents: [brief("chk", "checkout", "service")],
      applications: [],
      capabilities: [],
      processes: [],
    },
    ...over,
  };
}

describe("an incident, read as an analysis", () => {
  it("says what its sources say, each with its evidence", () => {
    const made = incidentAnalysis(incident(), t, links);

    expect(made.status).toBe("complete");
    expect(made.findings.map((f) => f.statement)).toEqual([
      "payment-api p99 latency above 2s : clos, sev2.",
      "Il a duré 4 h.",
      "Il touche payment-api.",
    ]);
    const [state, lasted, touches] = made.findings;
    // Its tool and name from the source, by id — not the key's kind.
    expect(state.evidence[0]).toMatchObject({
      kind: "record",
      label: "OPS-1841",
      source: { kind: "jira", name: "OPS board" },
      href: "https://acme.atlassian.net/browse/OPS-1841",
    });
    expect(lasted.evidence.map((e) => e.label)).toEqual(["Ouvert", "Résolu"]);
    expect(touches.evidence[0]).toMatchObject({
      label: "payment-api",
      href: "/environment/services/svc",
      facts: [{ label: "Lien", value: "Une source le déclare." }],
    });
    expect(made.recommendations).toEqual([]);
  });

  it("ranks the causes, the surest first, a source's word apart from an inference", () => {
    const made = incidentAnalysis(incident(), t, links);

    expect(made.causes.map((c) => [c.label, c.basis, c.confidence])).toEqual([
      ["payment-api v2.8.4", "stated", 0.83],
      ["Feature flag flipped", "inferred", 0.6],
    ]);
    const [deployed, flipped] = made.causes;
    expect(deployed.why).toBe("Une source le déclare.");
    expect(deployed.kind).toBe("Déploiement");
    // What changed just before it is its evidence; and the record saying so.
    expect(deployed.evidence.map((e) => e.label)).toEqual([
      "Déploiement · payment-api v2.8.4",
      "OPS-1841",
    ]);
    expect(flipped.why).toContain("LEKA le soupçonne");
    expect(made.confidence).toBe(0.83);
  });

  it("reads the risk from its severity, and what it reaches", () => {
    const made = incidentAnalysis(incident(), t, links);

    expect(made.impact?.risk).toBe("medium");
    expect(made.impact?.riskBasis).toBe("d'après la gravité déclarée (sev2)");
    expect(made.impact?.areas.map((a) => [a.label, a.items.map((i) => i.label)])).toEqual([
      ["Touché", ["payment-api"]],
      ["Qui en dépend", ["checkout"]],
      ["Applications", []],
      ["Capacités métier", []],
      ["Processus métier", []],
    ]);
    // A change before it that nothing ties to it: said, not guessed.
    expect(made.uncertainties).toEqual([
      "1 changement(s) juste avant lui, sans lien établi avec lui.",
    ]);
  });

  it("says what is only suspected, and what is missing", () => {
    const made = incidentAnalysis(
      incident({
        severity: null,
        suspected_causes: [{ entity: FLAG, origin: "inferred", rule: "preceded", confidence: 0.6 }],
        affected: [],
        changed_before: [],
      }),
      t,
      links,
    );

    expect(made.status).toBe("partial");
    expect(made.missing).toEqual(["ce qu'il touche"]);
    expect(made.impact?.risk).toBe("unknown");
    expect(made.uncertainties).toEqual([
      "Sa cause n'est que soupçonnée : aucune source ne la déclare.",
      "On ne sait pas ce qu'il touche : aucune source ne le relie à un service.",
      "Sa gravité n'est pas dite : le risque ne peut pas être évalué.",
    ]);
  });

  it("is inconclusive when it knows neither cause nor what is touched", () => {
    const made = incidentAnalysis(
      incident({ suspected_causes: [], affected: [], changed_before: [], state: null }),
      t,
      links,
    );

    expect(made.status).toBe("inconclusive");
    expect(made.missing).toEqual(["ce qui l'a causé", "ce qu'il touche"]);
    expect(made.findings[0].statement).toBe("payment-api p99 latency above 2s : sev2.");
    expect(made.confidence).toBeNull();
  });
});
