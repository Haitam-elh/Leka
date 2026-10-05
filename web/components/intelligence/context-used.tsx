"use client";

import { cn } from "cn";

import { UncertaintyList } from "@/components/intelligence/confidence";
import { timeAgo } from "@/components/knowledge/time";
import type { AssembledContext } from "@/lib/context";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * The context an output was made from (LEKA-341, LEKA-370/371/372): which
 * version, read from which build of the company model, what it holds — the
 * entities, the relationships stated and inferred, the sources, what was
 * left out and why — how it was searched, retriever by retriever, and what
 * that leaves uncertain: a retriever that failed, things left out, sources
 * that contradict each other.
 */

type Dictionary = ReturnType<typeof useDictionary>;

/** "il y a 3 min", inside a sentence — timeAgo says it at the start of one. */
function ago(t: Dictionary, iso: string): string {
  const said = timeAgo(t, iso);
  return said.charAt(0).toLocaleLowerCase() + said.slice(1);
}

export function retrieverName(t: Dictionary, name: string): string {
  return (t.intelligence.context.retrievers as Record<string, string>)[name] ?? name;
}

export function ContextVersionLine({ assembled }: { assembled: AssembledContext }) {
  const t = useDictionary();
  const w = t.intelligence.context;
  return (
    <span className="text-[0.8125rem] text-shell-muted" data-testid="context-version-line">
      {fill(w.versionLine, { version: assembled.version, ago: ago(t, assembled.assembled_at) })}
      {" · "}
      {assembled.model_built_at
        ? fill(w.modelLine, { ago: ago(t, assembled.model_built_at) })
        : w.noModel}
    </span>
  );
}

export function ContextUsedPanel({ assembled }: { assembled: AssembledContext }) {
  const t = useDictionary();
  const w = t.intelligence.context;
  const { summary } = assembled;
  const failed = assembled.retrieval.filter(
    (run) => run.status === "failed" || run.status === "timeout",
  );
  const uncertain = [
    ...failed.map((run) =>
      fill(w.retrieverMissing, { retriever: retrieverName(t, run.retriever) }),
    ),
    ...(assembled.truncated
      ? [fill(w.leftOut, { count: assembled.dropped, limit: assembled.request.limit })]
      : []),
    ...(assembled.conflicts?.length
      ? [fill(w.conflicts, { count: assembled.conflicts.length })]
      : []),
  ];
  // Why things were left out (LEKA-372) — or, before, the budget alone.
  const why = assembled.ranking?.left_out;
  const droppedNote = why
    ? fill(w.figures.droppedWhy, {
        duplicate: why.duplicate ?? 0,
        low: why.low_relevance ?? 0,
        budget: why.budget ?? 0,
      })
    : assembled.truncated
      ? fill(w.figures.droppedNote, { limit: assembled.request.limit })
      : undefined;
  return (
    <div className="space-y-2" data-testid="context-used">
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Figure label={w.figures.entities} value={summary.entities} />
        <Figure
          label={w.figures.relationships}
          value={summary.relationships}
          note={fill(w.figures.stated, { count: summary.stated, inferred: summary.inferred })}
        />
        <Figure
          label={w.figures.sources}
          value={assembled.sources.length}
          note={assembled.sources.map((s) => s.name ?? s.kind ?? w.deletedSource).join(", ")}
        />
        <Figure
          label={w.figures.dropped}
          value={assembled.dropped}
          note={droppedNote}
          warn={assembled.truncated}
        />
      </dl>
      {assembled.retrieval.length > 0 ? (
        <ul
          className="flex flex-wrap gap-1.5 text-xs"
          aria-label={w.retrieval}
          data-testid="context-retrieval"
        >
          {assembled.retrieval.map((run) => (
            <li
              key={run.retriever}
              title={run.error ?? run.detail ?? undefined}
              className={cn(
                "rounded-full px-2 py-0.5",
                run.status === "ok" && "bg-shell-canvas text-brand-navy",
                run.status === "skipped" && "bg-shell-canvas text-shell-muted",
                (run.status === "failed" || run.status === "timeout") &&
                  "bg-state-warning-soft text-state-warning",
              )}
            >
              {retrieverName(t, run.retriever)}
              {" · "}
              {run.status === "ok"
                ? fill(w.runFound, { count: run.found })
                : w.runStatus[run.status]}
            </li>
          ))}
        </ul>
      ) : null}
      <UncertaintyList items={uncertain} />
    </div>
  );
}

function Figure({
  label,
  value,
  note,
  warn,
}: {
  label: string;
  value: number;
  note?: string;
  warn?: boolean;
}) {
  return (
    // dt and dd straight in the tile — a <dl> takes a <div> per group, no
    // deeper — the grid putting the figure beside its label.
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-2 rounded-lg bg-shell-canvas px-3 py-1.5">
      <dt className="text-xs text-shell-muted">{label}</dt>
      <dd className={cn("font-semibold text-brand-navy", warn && "text-state-warning")}>
        {value}
      </dd>
      {note ? (
        <dd className="col-span-2 truncate text-xs text-shell-muted" title={note}>
          {note}
        </dd>
      ) : null}
    </div>
  );
}
