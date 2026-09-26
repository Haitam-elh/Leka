"use client";

import { KnowledgeTable, type KnowledgeColumn } from "@/components/knowledge/knowledge-table";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { timeAgo } from "@/components/knowledge/time";
import { capabilityWord } from "@/components/sources/source-panel";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { Source, SourceSync } from "@/lib/sources";
import { useSourceSyncs } from "@/lib/sources-queries";

/** The sync's own order: what the rest hangs from first. */
const ORDER = ["repositories", "branches", "commits", "pull_requests", "issues", "releases"];

/**
 * How far each capability of a source has been read (LEKA-352): its status,
 * its last success, what it brought, how many passes failed in a row and
 * why the last one did. Polled every few seconds while a pass runs, so a
 * "Synchroniser maintenant" is seen to happen.
 */
export function SourceSyncSection({ source }: { source: Source }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.sources.sync;
  const syncs = useSourceSyncs(source.id);
  const number = new Intl.NumberFormat(locale === "fr" ? "fr-FR" : "en-GB");

  const columns: KnowledgeColumn<SourceSync>[] = [
    {
      id: "capability",
      header: w.capability,
      cell: (sync) => capabilityWord(t, sync.capability),
      sortValue: (sync) => sync.capability,
    },
    {
      id: "status",
      header: w.status,
      cell: (sync) => (
        <div>
          <StatusBadge
            variant={`sync.${sync.status as "idle" | "running" | "failed"}`}
            size="sm"
            live={false}
          />
          {sync.last_error ? (
            <p className="mt-1 max-w-72 text-xs text-state-danger">
              {String(sync.last_error.message ?? "")}
            </p>
          ) : null}
        </div>
      ),
    },
    {
      id: "last-success",
      header: w.lastSuccess,
      cell: (sync) =>
        sync.last_succeeded_at ? timeAgo(t, sync.last_succeeded_at) : t.sources.never,
      sortValue: (sync) => sync.last_succeeded_at ?? "",
    },
    {
      id: "records",
      header: w.records,
      align: "end",
      cell: (sync) => number.format(sync.records_total),
      sortValue: (sync) => sync.records_total,
    },
    {
      id: "failures",
      header: w.failures,
      align: "end",
      cell: (sync) => sync.consecutive_failures,
    },
  ];

  const rows = syncs.data?.capabilities;
  const passState = syncs.data?.pass_state;
  const fullAt = rows
    ?.map((sync) => sync.last_full_at)
    .filter((at): at is string => at !== null)
    .sort()
    .at(0);

  return (
    <section className="rounded-xl border border-shell-line bg-white p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-brand-navy">{w.title}</h2>
          {passState === "running" ? <StatusBadge variant="sync.running" size="sm" live /> : null}
          {passState === "queued" ? (
            <span role="status" className="text-xs text-shell-muted">
              {w.queued}
            </span>
          ) : null}
        </div>
        {fullAt ? (
          <p className="text-xs text-shell-muted">
            {w.full} {fill(w.fullAt, { date: new Date(fullAt).toLocaleDateString(locale) })}
          </p>
        ) : null}
      </div>
      {syncs.isError ? (
        <p className="text-sm text-shell-muted">{w.loadFailed}</p>
      ) : rows && rows.length === 0 ? (
        <p className="text-sm text-shell-muted">{w.notYet}</p>
      ) : (
        <KnowledgeTable
          caption={w.title}
          columns={columns}
          rows={[...(rows ?? [])].sort(
            (a, b) => ORDER.indexOf(a.capability) - ORDER.indexOf(b.capability),
          )}
          rowKey={(sync) => sync.capability}
          loading={syncs.isPending}
        />
      )}
    </section>
  );
}
