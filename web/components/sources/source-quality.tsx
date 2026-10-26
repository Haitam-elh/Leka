"use client";

import { KnowledgeTable, type KnowledgeColumn } from "@/components/knowledge/knowledge-table";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { timeAgo } from "@/components/knowledge/time";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { Source, SourceValidation } from "@/lib/sources";
import { useSourceValidation } from "@/lib/sources-queries";

type IssueLine = SourceValidation["issues"][number];
type Quarantined = SourceValidation["quarantined_records"][number];
type Score = keyof SourceValidation["scores"];

const SEVERITY = {
  error: "sync.failed",
  warning: "source.attention",
  info: "source.off",
} as const;

const PARTS: Exclude<Score, "quality">[] = ["completeness", "consistency", "freshness", "confidence"];

/**
 * What a source's records are worth (LEKA-358): how many validated, doubtful,
 * quarantined; their quality and what makes it; the issues found, how often,
 * and what to do about each; the latest records kept out of the company
 * model until they are corrected.
 */
export function SourceQualitySection({ source }: { source: Source }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.sources.quality;
  const validation = useSourceValidation(source.id);
  const number = new Intl.NumberFormat(locale);
  const percent = (value: number | null | undefined) =>
    value === null || value === undefined ? "-" : `${Math.round(value * 100)} %`;
  const read = validation.data;
  const counted = read ? read.valid + read.warning + read.quarantined : 0;

  const issueColumns: KnowledgeColumn<IssueLine>[] = [
    {
      id: "issue",
      header: w.issue,
      cell: (line) => (w.codes as Record<string, string>)[line.code] ?? line.code,
    },
    {
      id: "severity",
      header: w.severity,
      cell: (line) => (
        <StatusBadge
          variant={SEVERITY[line.severity as keyof typeof SEVERITY] ?? "source.off"}
          label={(w.severities as Record<string, string>)[line.severity] ?? line.severity}
          size="sm"
        />
      ),
    },
    {
      id: "records",
      header: w.records,
      align: "end",
      cell: (line) => number.format(line.records),
    },
    {
      id: "remedy",
      header: w.remedy,
      cell: (line) => <span className="text-xs text-shell-muted">{line.remediation}</span>,
    },
  ];
  const quarantineColumns: KnowledgeColumn<Quarantined>[] = [
    {
      id: "element",
      header: w.element,
      cell: (row) => (
        <code className="text-xs break-all text-brand-navy">{row.entity_key ?? "-"}</code>
      ),
    },
    {
      id: "why",
      header: w.why,
      cell: (row) => (
        <ul className="text-xs text-shell-muted">
          {row.issues
            .filter((issue) => issue.severity === "error")
            .map((issue) => (
              <li key={`${String(issue.code)}-${String(issue.field)}`}>
                {(w.codes as Record<string, string>)[String(issue.code)] ?? String(issue.code)}
                {t.shell.colon}
                {String(issue.message)}
              </li>
            ))}
        </ul>
      ),
    },
  ];

  return (
    <section className="rounded-xl border border-shell-line bg-white p-4">
      <h2 className="mb-1 text-lg font-semibold text-brand-navy">{w.title}</h2>
      <p className="mb-3 text-sm text-shell-muted">{w.intro}</p>
      {validation.isError ? (
        <p className="text-sm text-shell-muted">{w.loadFailed}</p>
      ) : read && counted === 0 ? (
        <p className="text-sm text-shell-muted">{w.none}</p>
      ) : read ? (
        <div className="flex flex-col gap-4">
          <dl className="grid gap-2 sm:grid-cols-4">
            <Figure label={w.valid} value={number.format(read.valid)} />
            <Figure label={w.warning} value={number.format(read.warning)} />
            <Figure label={w.quarantined} value={number.format(read.quarantined)} />
            <Figure label={w.score} value={percent(read.scores.quality)} />
          </dl>
          <dl className="grid gap-2 text-sm sm:grid-cols-4">
            {PARTS.map((part) => (
              <div key={part} className="flex items-baseline justify-between gap-2">
                <dt className="text-shell-muted">{w.scores[part]}</dt>
                <dd className="font-medium text-brand-navy">{percent(read.scores[part])}</dd>
              </div>
            ))}
          </dl>
          {read.last_validated_at ? (
            <p className="text-xs text-shell-muted">{timeAgo(t, read.last_validated_at)}</p>
          ) : null}
          {read.issues.length > 0 ? (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-brand-navy">{w.issues}</h3>
              <KnowledgeTable
                caption={w.caption}
                columns={issueColumns}
                rows={read.issues}
                rowKey={(line) => `${line.code}-${line.severity}`}
              />
            </div>
          ) : null}
          {read.quarantined_records.length > 0 ? (
            <div>
              <h3 className="mb-2 text-sm font-semibold text-brand-navy">{w.quarantine}</h3>
              <KnowledgeTable
                caption={w.quarantineCaption}
                columns={quarantineColumns}
                rows={read.quarantined_records}
                rowKey={(row) => `${row.entity_key ?? ""}-${row.validated_at}`}
              />
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-shell-line p-3">
      <dt className="text-xs text-shell-muted">{label}</dt>
      <dd className="text-xl font-semibold text-brand-navy">{value}</dd>
    </div>
  );
}
