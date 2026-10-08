/**
 * A proposal in the reader's words (LEKA-380), from its code and values —
 * its English statement when the interface does not know the code yet.
 */

import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import type { Candidate } from "@/lib/enrichment";
import { modelTitle } from "@/lib/models";

export interface Worded {
  /** What it proposes: "acme/user-service est le code de user-service". */
  title: string;
  /** Why, in a few words: "D'après le nom du dépôt". */
  why: string | null;
}

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

export function levelWord(t: Dictionary, level: unknown): string {
  const levels = t.approvals.words.levels as Record<string, string>;
  return levels[text(level)] ?? text(level);
}

export function wordCandidate(t: Dictionary, candidate: Candidate): Worded {
  const p = candidate.params;
  const w = t.approvals.words;
  const name = text(p.name) || candidate.subject.name;
  switch (candidate.code) {
    case "enrichment.code":
      return {
        title: fill(w.code, { repository: text(p.repository), name }),
        why: w.codeWhy,
      };
    case "enrichment.runtime":
      return { title: fill(w.runtime, { name, resource: text(p.resource) }), why: w.runtimeWhy };
    case "enrichment.owner":
      return {
        title: fill(w.owner, { team: text(p.team), name }),
        why:
          p.how === "repository"
            ? fill(w.ownerRepository, { team: text(p.team), repository: text(p.repository) })
            : fill(w.ownerMaintainers, {
                members: text(p.members),
                maintainers: text(p.maintainers),
                team: text(p.team),
              }),
      };
    case "enrichment.application":
      return {
        title: fill(w.application, { name, application: text(p.application) }),
        why:
          p.how === "neighbours"
            ? fill(w.applicationNeighbours, { count: text(p.count), of: text(p.of) })
            : w.applicationName,
      };
    case "enrichment.criticality": {
      const level = levelWord(t, p.level);
      return {
        title: p.current
          ? fill(w.criticalityOver, { name, level, current: levelWord(t, p.current) })
          : fill(w.criticality, { name, level }),
        why:
          p.from === "application"
            ? fill(w.criticalityApplication, { application: text(p.application), level })
            : fill(w.criticalityReliance, { count: text(p.relying) }),
      };
    }
    case "enrichment.description":
      return {
        title: fill(w.description, { name }),
        why: fill(w.descriptionWhy, { repository: text(p.repository) }),
      };
    case "enrichment.summary":
      // Written by a language model from what LEKA knows of it (LEKA-394).
      return {
        title: fill(w.description, { name }),
        why: fill(w.summaryWhy, {
          model: modelTitle(text(p.model) || "model"),
          facts: text(p.facts),
        }),
      };
    default:
      return { title: candidate.statement, why: null };
  }
}
