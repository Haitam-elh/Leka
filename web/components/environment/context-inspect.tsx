"use client";

import { ExternalLink } from "lucide-react";
import { useState } from "react";

import { cn } from "cn";

import { qualityGapSaid } from "@/components/environment/context-quality";
import { Pill } from "@/components/intelligence";
import { exactDate } from "@/components/knowledge/time";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import type { EvidenceRecord } from "@/lib/context";
import { useElementEvidence, useElementInspection } from "@/lib/context-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";

/**
 * One element of a context, inspected (LEKA-376), under its provenance on
 * the Contexte tab: how it stood in each version of the context — its
 * rank, absent, what changed of it — what the version's quality says of it,
 * what people said of it; and, on asking, the source records it was read
 * from — their source, title, date, the start of their text, a way to open
 * them where they live, said gone when the source no longer shows them.
 * Nothing is drawn that the API did not say.
 */

export function ElementInspect({
  contextId,
  version,
  refId,
}: {
  contextId: string;
  version: number;
  refId: string;
}) {
  const t = useDictionary();
  const w = t.environment.sheet.context.inspect;
  const triggers = t.environment.sheet.context.trigger as Record<string, string>;
  const fields = t.environment.sheet.context.fields as Record<string, string>;
  const inspected = useElementInspection(contextId, refId, version);
  const [asked, setAsked] = useState(false);
  const data = inspected.data;
  if (!data) return null;
  const names = new Map([[refId, data.element.label]]);
  const said = [
    ...data.quality.gaps.map((gap) => qualityGapSaid(t, gap, names)),
    ...data.quality.conflicts.map((conflict) =>
      fill(w.conflict, {
        about: conflict.about,
        severity: t.quality.gaps.severity[conflict.severity],
      }),
    ),
  ];
  const field = (name: string) =>
    name.startsWith("attributes.") ? name.slice("attributes.".length) : (fields[name] ?? name);
  return (
    <section
      aria-label={w.title}
      className="mt-2 ml-6 space-y-2 rounded-md bg-shell-canvas/60 p-2 text-xs"
      data-testid="element-inspect"
    >
      <div>
        <p className="font-semibold text-brand-navy">{w.history}</p>
        <ol className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5" data-testid="element-history">
          {data.history.map((step) => (
            <li key={step.version} className={cn(!step.held && "text-shell-muted")}>
              {fill(w.step, {
                version: step.version,
                trigger: triggers[step.trigger] ?? step.trigger,
              })}
              {" · "}
              {step.held && step.rank
                ? fill(w.rank, { rank: step.rank })
                : step.held
                  ? w.held
                  : w.absent}
              {(step.changed ?? []).length > 0
                ? ` · ${fill(w.changed, { fields: (step.changed ?? []).map(field).join(", ") })}`
                : ""}
            </li>
          ))}
        </ol>
      </div>
      <div>
        <p className="font-semibold text-brand-navy">{w.quality}</p>
        {said.length > 0 ? (
          <ul data-testid="element-quality">
            {said.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : (
          <p className="text-shell-muted">{w.nothing}</p>
        )}
        <p className="mt-0.5 text-shell-muted" data-testid="element-feedback-counts">
          {fill(w.feedback, { ...data.feedback })}
        </p>
      </div>
      {asked ? (
        <Evidence contextId={contextId} version={version} refId={refId} />
      ) : (
        <Button type="button" size="sm" variant="outline" onClick={() => setAsked(true)}>
          {w.evidence.show}
        </Button>
      )}
    </section>
  );
}

function Evidence({
  contextId,
  version,
  refId,
}: {
  contextId: string;
  version: number;
  refId: string;
}) {
  const t = useDictionary();
  const w = t.environment.sheet.context.inspect.evidence;
  const evidence = useElementEvidence(contextId, refId, version, true);
  if (evidence.isError) {
    return (
      <p className="text-state-danger" role="alert">
        {evidence.error instanceof ApiError && evidence.error.status === 403
          ? w.forbidden
          : w.failed}
      </p>
    );
  }
  if (!evidence.data) return <p className="text-shell-muted">…</p>;
  const records = evidence.data.records;
  return (
    <div data-testid="element-evidence">
      <p className="font-semibold text-brand-navy">{fill(w.title, { count: records.length })}</p>
      {records.length === 0 ? (
        <p className="text-shell-muted">{w.none}</p>
      ) : (
        <ul className="mt-1 space-y-1.5">
          {records.map((record) => (
            <EvidenceLine key={`${record.source_id}-${record.external_id}`} record={record} />
          ))}
        </ul>
      )}
      {evidence.data.truncated ? (
        <p className="mt-1 text-shell-muted">{fill(w.truncated, { count: records.length })}</p>
      ) : null}
    </div>
  );
}

function EvidenceLine({ record }: { record: EvidenceRecord }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.environment.sheet.context.inspect.evidence;
  const when = record.updated_at ?? record.created_at;
  return (
    <li data-testid="evidence-record" data-gone={record.gone}>
      <span className="flex flex-wrap items-center gap-x-2">
        <span className="font-medium text-brand-navy">{record.title ?? record.external_id}</span>
        <span className="text-shell-muted">
          {[record.source_name ?? w.deleted, record.state, when ? exactDate(locale, when) : null]
            .filter(Boolean)
            .join(" · ")}
        </span>
        {record.gone ? <Pill tone="warning">{w.gone}</Pill> : null}
        {record.url ? (
          <a
            href={record.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          >
            {w.open}
            <ExternalLink className="size-3" aria-hidden="true" />
          </a>
        ) : null}
      </span>
      {record.excerpt ? (
        <span className="mt-0.5 line-clamp-3 block text-shell-muted">{record.excerpt}</span>
      ) : null}
    </li>
  );
}
