"use client";

import { KnowledgeTable, type KnowledgeColumn } from "@/components/knowledge/knowledge-table";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { exactDate, timeAgo } from "@/components/knowledge/time";
import { capabilityWord } from "@/components/sources/source-panel";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { Source, SyncRun } from "@/lib/sources";
import { useSourceRuns } from "@/lib/sources-queries";

/**
 * A source's latest passes (LEKA-353): when, started by what, full or since
 * the last one, how long, what they read, how they ended. The newest, while
 * it runs, says what it is reading and how far it has got — polled every
 * few seconds, from the progress each committed batch records.
 */
export function SourceRunsSection({ source }: { source: Source }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.sources.runs;
  const runs = useSourceRuns(source.id);
  const number = new Intl.NumberFormat(locale);
  const running = runs.data?.[0]?.status === "running" ? runs.data[0] : null;
  const labels: Record<Outcome, string> = {
    running: w.running,
    succeeded: w.succeeded,
    failed: w.failed,
    abandoned: w.abandoned,
  };

  const columns: KnowledgeColumn<SyncRun>[] = [
    {
      id: "started",
      header: w.started,
      cell: (run) => (
        <span title={exactDate(locale, run.started_at)}>{timeAgo(t, run.started_at)}</span>
      ),
    },
    {
      id: "trigger",
      header: w.trigger,
      cell: (run) => (w.triggers as Record<string, string>)[run.trigger] ?? run.trigger,
    },
    { id: "kind", header: w.kind, cell: (run) => (run.full_read ? w.full : w.incremental) },
    { id: "duration", header: w.duration, align: "end", cell: (run) => duration(run) },
    { id: "records", header: w.records, align: "end", cell: (run) => number.format(run.records) },
    { id: "size", header: w.size, align: "end", cell: (run) => size(run.bytes, number) },
    {
      id: "status",
      header: w.status,
      cell: (run) => (
        <div>
          <StatusBadge
            variant={RESULT[run.status as Outcome] ?? "sync.failed"}
            label={labels[run.status as Outcome]}
            size="sm"
          />
          {run.error && run.status === "failed" ? (
            <p className="mt-1 max-w-64 text-xs text-state-danger">
              {String(run.error.message ?? "")}
            </p>
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <section className="rounded-xl border border-shell-line bg-white p-4">
      <h2 className="mb-3 text-lg font-semibold text-brand-navy">{w.title}</h2>
      {running?.capability ? (
        <p role="status" className="mb-3 text-sm text-brand-navy">
          {fill(w.progress, {
            capability: capabilityWord(t, running.capability, source.type),
            records: number.format(running.records),
          })}
        </p>
      ) : null}
      {runs.isError ? (
        <p className="text-sm text-shell-muted">{w.loadFailed}</p>
      ) : runs.data && runs.data.length === 0 ? (
        <p className="text-sm text-shell-muted">{w.empty}</p>
      ) : (
        <KnowledgeTable
          caption={w.caption}
          columns={columns}
          rows={runs.data ?? []}
          rowKey={(run) => run.id}
          loading={runs.isPending}
        />
      )}
    </section>
  );
}

type Outcome = "running" | "succeeded" | "failed" | "abandoned";

const RESULT = {
  running: "sync.running",
  succeeded: "source.synced",
  failed: "sync.failed",
  abandoned: "source.attention",
} as const satisfies Record<Outcome, string>;

/** "4 min 12 s", "1 h 05 min"; running: so far. */
function duration(run: SyncRun): string {
  const end = run.finished_at ? Date.parse(run.finished_at) : Date.now();
  const seconds = Math.max(0, Math.round((end - Date.parse(run.started_at)) / 1000));
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ${String(seconds % 60).padStart(2, "0")} s`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")} min`;
}

function size(bytes: number, number: Intl.NumberFormat): string {
  if (bytes < 1024) return `${number.format(bytes)} o`;
  if (bytes < 1024 ** 2) return `${number.format(Math.round(bytes / 1024))} Ko`;
  return `${number.format(Math.round((bytes / 1024 ** 2) * 10) / 10)} Mo`;
}
