"use client";

import { ChevronDown, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { cn } from "cn";

import { Pill, retrieverName } from "@/components/intelligence";
import type { AssembledContext, ContextElement } from "@/lib/context";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * How a context was ranked, on its tab (LEKA-372): each element's score,
 * its place and every signal it was read from — how much it is about the
 * request, how far it can be relied on — what was folded into it as
 * probably the same; what its sources disagree on, every side with who
 * says so; and what was left out, and why. All of it as the API says it:
 * a version made before LEKA-372 says nothing of a ranking it never had.
 */

type Dictionary = ReturnType<typeof useDictionary>;
type Ranking = NonNullable<ContextElement["ranking"]>;
type Signal = Ranking["signals"][number];
type Conflict = NonNullable<AssembledContext["conflicts"]>[number];

const percent = (value: number) => Math.round(value * 100);

/** On a row: its score, a conflict, what was folded into it. */
export function RowMarks({ element }: { element: ContextElement }) {
  const t = useDictionary();
  const w = t.environment.sheet.context;
  const ranking = element.ranking;
  const score = ranking ? ranking.score : element.relevance;
  return (
    <>
      {ranking?.conflicts?.length ? (
        <Pill tone="warning" data-testid="element-disputed">
          <TriangleAlert className="size-3" aria-hidden="true" />
          {w.ranking.disputed}
        </Pill>
      ) : null}
      {ranking?.duplicates?.length ? (
        <span className="shrink-0 text-xs text-shell-muted">
          {fill(w.ranking.folded, { count: ranking.duplicates.length })}
        </span>
      ) : null}
      {score !== null && score !== undefined && element.kind === "entity" ? (
        <span
          className="shrink-0 rounded bg-brand-violet-soft px-1.5 text-xs font-medium text-shell-nav-active tabular-nums"
          title={w.relevance}
          data-testid="element-score"
        >
          {percent(score)} %
        </span>
      ) : null}
    </>
  );
}

/** "Pourquoi ce rang", inside an element's provenance: its terms, a dl's. */
export function RankWhy({ ranking }: { ranking: Ranking }) {
  const t = useDictionary();
  const w = t.environment.sheet.context.ranking;
  const duplicates = ranking.duplicates ?? [];
  const topic = ranking.signals.filter((s) => s.axis === "topic");
  const trust = ranking.signals.filter((s) => s.axis === "trust");
  return (
    <>
      <dt className="text-shell-muted">{w.title}</dt>
      <dd data-testid="element-ranking">
        <p className="font-medium text-brand-navy">
          {ranking.rank
            ? fill(w.rankLine, { rank: ranking.rank, score: percent(ranking.score) })
            : fill(w.tieLine, { score: percent(ranking.score) })}
        </p>
        <Axis label={w.topic} value={ranking.topic} signals={topic} />
        <Axis label={w.trust} value={ranking.trust} signals={trust} />
      </dd>
      {duplicates.length > 0 ? (
        <>
          <dt className="text-shell-muted">{w.duplicates}</dt>
          <dd>
            {duplicates
              .map((d) =>
                fill(w.duplicate, {
                  label: d.label,
                  rule: d.rule,
                  confidence: percent(d.confidence),
                }),
              )
              .join(" · ")}
          </dd>
        </>
      ) : null}
    </>
  );
}

function Axis({
  label,
  value,
  signals,
}: {
  label: string;
  value: number | null;
  signals: readonly Signal[];
}) {
  const t = useDictionary();
  const w = t.environment.sheet.context.ranking;
  return (
    <div className="mt-1">
      <p className="text-shell-muted">
        {label} ·{" "}
        <span className="text-brand-navy tabular-nums">
          {value === null ? w.unknown : `${percent(value)} %`}
        </span>
      </p>
      <ul className="mt-0.5 space-y-0.5">
        {signals.map((signal) => (
          <li key={signal.name} className="flex gap-2" data-testid="ranking-signal">
            <span className="w-24 shrink-0 text-shell-muted">
              {(w.signals as Record<string, string>)[signal.name] ?? signal.name}
            </span>
            <span className="w-10 shrink-0 text-right tabular-nums">
              {signal.value === null ? "—" : `${percent(signal.value)} %`}
            </span>
            <span className="min-w-0">{said(t, signal)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A signal in words, from what it was read from. */
export function said(t: Dictionary, signal: Signal): string {
  const w = t.environment.sheet.context.ranking.said;
  const states = t.environment.sheet.context.ranking.states as Record<string, string>;
  const detail = signal.detail as Record<string, unknown>;
  const value = signal.value === null ? null : percent(signal.value);
  switch (signal.name) {
    case "asked":
      return w.asked;
    case "retrieval": {
      const matches = Array.isArray(detail.matches)
        ? (detail.matches as { retriever: string; rank: number }[])
        : [];
      return matches.length
        ? matches
            .map((m) => fill(w.match, { retriever: retrieverName(t, m.retriever), rank: m.rank }))
            .join(", ")
        : w.notFound;
    }
    case "proximity": {
      if (detail.steps === undefined) return w.untied;
      return detail.near
        ? fill(w.steps, { steps: String(detail.steps), near: String(detail.near) })
        : fill(w.stepsAway, { steps: String(detail.steps) });
    }
    case "ends":
      return fill(w.ends, { end: String(detail.end ?? "") });
    case "confidence":
      return fill(w.confidence, { value: value ?? 0 });
    case "quality":
      return value === null ? w.noQuality : fill(w.quality, { value });
    case "freshness": {
      if (value === null) return w.neverSeen;
      const days = Math.round(Number(detail.days ?? 0));
      return days < 1 ? w.freshToday : fill(w.freshness, { days });
    }
    case "sources": {
      if (value === null) return w.noSourceState;
      if (detail.status === "deleted") return w.deletedSource;
      const status = [detail.status, detail.health]
        .filter((part): part is string => typeof part === "string")
        .map((part) => states[part] ?? part)
        .join(", ");
      return fill(w.source, { name: String(detail.source ?? ""), status });
    }
    case "corroboration":
      return Number(detail.sources ?? 0) > 0
        ? fill(w.corroboration, { count: Number(detail.sources) })
        : w.noSource;
    case "lifecycle": {
      const lifecycles = t.environment.sheet.context.ranking.lifecycles as Record<string, string>;
      const state = String(detail.lifecycle ?? "");
      return lifecycles[state] ?? state;
    }
    case "consistency": {
      const disputed = Array.isArray(detail.disputed) ? (detail.disputed as string[]) : [];
      return disputed.length ? fill(w.disputed, { what: disputed.join(", ") }) : w.consistent;
    }
    case "origin":
      return detail.origin === "stated"
        ? w.stated
        : fill(w.inferred, { rule: String(detail.rule ?? "") });
    default:
      return signal.said;
  }
}

/** What the context's sources disagree on: every side, and who says so. */
export function ConflictsPanel({ assembled }: { assembled: AssembledContext }) {
  const t = useDictionary();
  const w = t.environment.sheet.context.conflictsPanel;
  const conflicts = assembled.conflicts ?? [];
  if (conflicts.length === 0) return null;
  return (
    <section
      aria-label={fill(w.title, { count: conflicts.length })}
      className="rounded-lg border border-state-warning/40 bg-state-warning-soft/30 p-3 text-xs"
      data-testid="context-conflicts"
    >
      <h3 className="mb-2 flex items-center gap-1.5 text-[0.8125rem] font-semibold text-brand-navy">
        <TriangleAlert className="size-4 text-state-warning" aria-hidden="true" />
        {fill(w.title, { count: conflicts.length })}
      </h3>
      <ul className="space-y-2">
        {conflicts.map((conflict) => (
          <ConflictRow key={conflict.id} conflict={conflict} />
        ))}
      </ul>
    </section>
  );
}

function ConflictRow({ conflict }: { conflict: Conflict }) {
  const t = useDictionary();
  const w = t.environment.sheet.context.conflictsPanel;
  const about = (w.about as Record<string, string>)[conflict.about] ?? conflict.about;
  const who = (by: readonly string[]) =>
    by
      .map((name) =>
        name === "a deleted source"
          ? w.deletedSource
          : name.startsWith("rule ")
            ? fill(w.rule, { rule: name.slice("rule ".length) })
            : name,
      )
      .join(", ");
  return (
    <li data-testid="context-conflict" data-kind={conflict.kind}>
      <p className="font-medium text-brand-navy">
        {conflict.label} · {about}
      </p>
      <p className="text-shell-muted">{(w.kinds as Record<string, string>)[conflict.kind]}</p>
      <ul className="mt-0.5">
        {conflict.values.map((side, index) => (
          <li key={`${index}-${String(side.value)}`}>
            <span className="font-medium">
              {conflict.kind === "gone" && side.value === "removed" ? w.removed : String(side.value)}
            </span>
            {conflict.chosen !== null &&
            conflict.chosen !== undefined &&
            JSON.stringify(conflict.chosen) === JSON.stringify(side.value) ? (
              <span className="text-shell-muted"> ({w.chosen})</span>
            ) : null}
            {side.by.length > 0 ? (
              <span className="text-shell-muted"> · {fill(w.by, { by: who(side.by) })}</span>
            ) : null}
          </li>
        ))}
      </ul>
    </li>
  );
}

/** What was left out, counted by why — the list on asking. */
export function LeftOutPanel({ assembled }: { assembled: AssembledContext }) {
  const t = useDictionary();
  const w = t.environment.sheet.context.leftPanel;
  const [open, setOpen] = useState(false);
  const ranking = assembled.ranking;
  if (!ranking) return null;
  const counts = ranking.left_out;
  const entities =
    (counts.duplicate ?? 0) +
    (counts.low_relevance ?? 0) +
    (counts.out_of_scope ?? 0) +
    (counts.budget ?? 0);
  const names = new Map(assembled.elements.map((e) => [e.ref_id, e.label]));
  const reasons = w.reasons as Record<string, string>;
  return (
    <section
      aria-label={fill(w.title, { count: entities })}
      className="rounded-lg border border-shell-line p-3 text-xs"
      data-testid="context-left-out"
    >
      <h3 className="mb-1 text-[0.8125rem] font-semibold text-brand-navy">
        {fill(w.title, { count: entities })}
      </h3>
      <p className="text-shell-muted">
        {fill(w.policy, {
          min: percent(ranking.min_relevance),
          share: percent(ranking.trust_share),
        })}
      </p>
      <ul className="mt-1 space-y-0.5">
        {(["duplicate", "low_relevance", "out_of_scope", "budget"] as const)
          // Outside the sources read: only when some were asked (LEKA-373).
          .filter((reason) => reason !== "out_of_scope" || (counts.out_of_scope ?? 0) > 0)
          .map((reason) => (
            <li key={reason} className="flex justify-between gap-2">
              <span>{reasons[reason]}</span>
              <span className="tabular-nums">{counts[reason] ?? 0}</span>
            </li>
          ))}
      </ul>
      {counts.ties ? (
        <p className="mt-0.5 text-shell-muted">{fill(w.ties, { count: counts.ties })}</p>
      ) : null}
      {ranking.left.length > 0 ? (
        <>
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            className="mt-2 flex items-center gap-1 rounded font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          >
            {open ? w.hide : w.show}
            <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} />
          </button>
          {open ? (
            <ul className="mt-1 max-h-48 space-y-1 overflow-y-auto" data-testid="left-out-list">
              {ranking.left.map((item) => (
                <li key={`${item.reason}-${item.ref_id}`}>
                  <span className="font-medium text-brand-navy">{item.label}</span>
                  <span className="text-shell-muted">
                    {" · "}
                    {reasons[item.reason]} · {percent(item.score)} %
                    {item.duplicate_of
                      ? ` · ${fill(w.of, { label: names.get(item.duplicate_of) ?? "" })}`
                      : ""}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
