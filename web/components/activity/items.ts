/**
 * Activité's lines in the reader's words (LEKA-383): each event the API
 * keeps — a build, an incident, an analysis, a finding, a decision — as a
 * title, what it says more, and where it leads. A finding is worded as
 * Insights words it, so the two never disagree.
 */

import { aboutWord } from "@/components/approvals/items";
import { word } from "@/components/insights/leka-insights";
import { routes } from "@/config/routes";
import type { ActivityCount, ActivityItem } from "@/lib/activity";
import { typeSegment } from "@/lib/environment";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import type { Finding } from "@/lib/insights";

export interface WordedItem {
  title: string;
  detail: string | null;
  href: string | null;
}

const COUNTS = [
  "created",
  "changed",
  "returned",
  "relationships_added",
  "relationships_changed",
  "relationships_removed",
] as const;

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function entityHref(kind: string | null | undefined, id: string | null | undefined): string | null {
  return kind && id ? routes.entity(typeSegment(kind), id) : null;
}

/** Where a restore is told: the thing's Historique. */
function historyHref(item: ActivityItem): string | null {
  const subject = item.subject;
  return subject?.kind && subject.id
    ? routes.entity(typeSegment(subject.kind), subject.id, "history")
    : null;
}

function subjectHref(item: ActivityItem): string | null {
  const subject = item.subject;
  if (!subject) return null;
  if (subject.type === "coverage") return routes.sources();
  if (subject.type === "source") return subject.id ? routes.source(subject.id) : null;
  return subject.type === "entity" ? entityHref(subject.kind, subject.id) : null;
}

/** An event in the reader's words: what it is, what it says more, where
 * it leads. */
export function wordActivity(t: Dictionary, item: ActivityItem): WordedItem {
  const w = t.activity.items;
  const p = item.params;
  const name = item.subject?.name ?? text(p.name);
  const status = text(p.status);
  // A proposal, a conflict: about what, in the reader's words — never the
  // API's English statement.
  const family = (t.approvals.family as Record<string, string>)[text(p.family)] ?? "";
  const proposed = [name, family].filter(Boolean).join(" · ") || null;
  const disputed = [aboutWord(t, text(p.about)), name].filter(Boolean).join(" · ") || null;
  switch (item.kind) {
    case "model_built": {
      const said = COUNTS.filter((key) => Number(p[key]) > 0).map((key) =>
        fill(w.counts[key], { count: text(p[key]) }),
      );
      const names = Array.isArray(p.names) ? p.names.map(text).filter(Boolean) : [];
      return {
        title: w.model_built,
        detail: [names.join(", "), said.join(", ")].filter(Boolean).join(" · ") || null,
        href: null,
      };
    }
    case "entity_removed":
      return {
        title: fill(w.entity_removed, { name }),
        detail: w.entityRemovedDetail,
        href: subjectHref(item),
      };
    case "incident":
      return {
        title: fill(w.incident, { name }),
        detail: [text(p.name), text(p.severity)].filter(Boolean).join(" · ") || null,
        href: entityHref("incident", text(p.event_id)),
      };
    case "deployment": {
      const state = text(p.state);
      return {
        title:
          state === "succeeded"
            ? w.deploymentSucceeded
            : state === "failed"
              ? w.deploymentFailed
              : w.deployment,
        detail: [text(p.name), text(p.environment)].filter(Boolean).join(" · ") || null,
        href: entityHref("deployment", text(p.event_id)),
      };
    }
    case "change":
    case "release":
      return {
        title: w[item.kind],
        detail: text(p.name) || null,
        href: entityHref(item.kind, text(p.event_id)),
      };
    case "analysis":
      return {
        title: w.analysis,
        detail: fill(w.analysisDetail, {
          opened: text(p.opened) || "0",
          resolved: text(p.resolved) || "0",
        }),
        href: null,
      };
    case "finding": {
      const finding = {
        code: text(p.code),
        params: (p.params as Record<string, unknown> | undefined) ?? {},
        statement: text(p.statement),
        severity: text(p.severity) || "low",
        category: text(p.category),
        subject: item.subject,
      } as unknown as Finding;
      const worded = word(t, finding);
      return { title: worded.title, detail: worded.detail, href: subjectHref(item) };
    }
    case "proposal":
      return {
        title: w.proposal,
        detail: proposed,
        href: routes.approval(text(p.candidate_id)),
      };
    case "decision":
      return {
        title: status === "rejected" ? w.rejected : w.accepted,
        detail: proposed,
        href: routes.approval(text(p.candidate_id)),
      };
    case "conflict":
      return {
        title: w.conflict,
        detail: disputed,
        href: `${routes.approval(text(p.conflict_id))}?kind=conflict`,
      };
    case "conflict_decision":
      return {
        title: status === "dismissed" ? w.dismissed : status === "open" ? w.reopened : w.resolved,
        detail: disputed,
        href: `${routes.approval(text(p.conflict_id))}?kind=conflict`,
      };
    case "restore":
      return {
        title: fill(w.restore, { version: text(p.version), name }),
        detail: null,
        href: historyHref(item),
      };
    case "undo":
      return {
        title: fill(w.undo, { name }),
        detail: null,
        href: historyHref(item),
      };
    case "source_event":
      return {
        title: (t.overview.events as Record<string, string>)[text(p.type)] ?? text(p.type),
        detail: text(p.name) || null,
        href: item.subject?.id ? routes.source(item.subject.id) : null,
      };
    case "rebuild":
      return {
        title: w.rebuild,
        detail: (w.rebuildStatus as Record<string, string>)[status] ?? null,
        href: null,
      };
    default:
      return { title: name, detail: null, href: subjectHref(item) };
  }
}

/** A person as the shell names them: their name — or, for an account that
 * gave none, the first part of its address, capitalised. */
export function personName(name: string): string {
  if (!name.includes("@")) return name;
  const local = name.split("@")[0] ?? name;
  return local.charAt(0).toUpperCase() + local.slice(1);
}

/** Who did it: "par Nora", "automatiquement" — or nothing for LEKA and
 * the sources. */
export function byWho(t: Dictionary, item: ActivityItem): string | null {
  if (item.via === "policy") return t.activity.latest.policy;
  if (item.via === "person" && item.by_name) {
    return fill(t.activity.latest.by, { name: personName(item.by_name) });
  }
  return null;
}

/** Below this many before, a percentage says more about the small number
 * than about the change: the difference is said instead. */
const SMALL = 10;

/** "+12 %", "−27 %" against the period before; "+34", "−2" when there were
 * few before; nothing when there is nothing either side. */
export function delta(count: ActivityCount): { text: string; up: boolean } | null {
  const difference = count.value - count.previous;
  if (count.previous < SMALL) {
    if (!count.value && !count.previous) return null;
    return {
      text: `${difference >= 0 ? "+" : "−"}${Math.abs(difference)}`,
      up: difference >= 0,
    };
  }
  const change = Math.round((difference / count.previous) * 100);
  if (change === 0) return { text: "0 %", up: true };
  return { text: `${change > 0 ? "+" : "−"}${Math.abs(change)} %`, up: change > 0 };
}

/** The latest events as a CSV a spreadsheet opens: one line each. */
export function toCsv(t: Dictionary, items: readonly ActivityItem[]): string {
  const c = t.activity.csv;
  const cell = (value: string) => `"${value.replaceAll('"', '""')}"`;
  const lines = items.map((item) => {
    const worded = wordActivity(t, item);
    return [
      item.at,
      t.activity.category[item.category],
      worded.title,
      worded.detail ?? "",
      item.subject?.name ?? "",
      item.by_name ? personName(item.by_name) : "",
    ]
      .map(cell)
      .join(",");
  });
  return [[c.at, c.category, c.title, c.detail, c.subject, c.by].map(cell).join(","), ...lines].join(
    "\n",
  );
}
