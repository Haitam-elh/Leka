"use client";

import { typeLabel } from "@/components/environment/parts";
import { hasSourceLogo, SourceLogo } from "@/components/sources/source-logo";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { KindCoverage, ViewSource } from "@/lib/knowledge-graph";
import type { SourceKind } from "@/lib/sources";
import { useSources } from "@/lib/sources-queries";

const MEASURES = ["owned", "documented", "corroborated", "connected"] as const;

/**
 * How well LEKA knows what a view shows, and where it comes from
 * (LEKA-369): for each kind, how many there are, and the share with an
 * owner, documented, confirmed by two sources, related to anything — over
 * all of them, not only those drawn, and it says so. Then the sources the
 * view is made of.
 * A measure that does not apply to a kind says so; nothing is estimated.
 */
export function CoveragePanel({
  coverage,
  sources,
}: {
  coverage: readonly KindCoverage[];
  sources: readonly ViewSource[];
}) {
  const t = useDictionary();
  const w = t.environment.coverage;
  const known = useSources();
  const names = new Map((known.data ?? []).map((source) => [source.id, source.display_name]));

  return (
    <div className="mt-4 border-t border-shell-line/60 pt-4" data-testid="coverage">
      <h3 className="text-[0.875rem] font-semibold text-brand-navy">{w.title}</h3>
      <p className="mb-2 text-xs text-shell-muted">{w.scope}</p>
      {coverage.length === 0 ? (
        <p className="text-[0.8125rem] text-shell-muted">{w.empty}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] text-start text-[0.8125rem]">
            <caption className="sr-only">{w.caption}</caption>
            <thead>
              <tr className="text-xs text-shell-muted">
                <th scope="col" className="py-1 pe-3 font-medium">
                  {w.kind}
                </th>
                <th scope="col" className="py-1 pe-3 font-medium">
                  {w.total}
                </th>
                {MEASURES.map((measure) => (
                  <th key={measure} scope="col" className="py-1 pe-3 font-medium">
                    {w[measure]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {coverage.map((row) => (
                <tr
                  key={row.type}
                  className="border-t border-shell-line/40"
                  data-testid={`coverage-${row.type}`}
                >
                  <th scope="row" className="py-1.5 pe-3 font-medium text-brand-navy">
                    {typeLabel(t, row.type)}
                  </th>
                  <td className="py-1.5 pe-3 text-brand-navy">{row.total}</td>
                  {MEASURES.map((measure) => (
                    <td key={measure} className="py-1.5 pe-3">
                      <Share label={w[measure]} part={row[measure]} total={row.total} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="mt-4 mb-2 text-[0.875rem] font-semibold text-brand-navy">{w.sources}</h3>
      {sources.length === 0 ? (
        <p className="text-[0.8125rem] text-shell-muted">{w.noSources}</p>
      ) : (
        <ul className="flex flex-wrap gap-2" aria-label={w.sources}>
          {sources.map((source) => (
            <li
              key={source.source_id}
              className="flex items-center gap-1.5 rounded-lg border border-shell-line px-2 py-1 text-xs text-brand-navy"
            >
              {hasSourceLogo(source.kind) ? (
                <SourceLogo kind={source.kind as SourceKind} className="size-4" />
              ) : null}
              <span className="font-medium">{names.get(source.source_id) ?? source.kind}</span>
              <span className="text-shell-muted">
                {fill(w.sourceEntities, { count: source.entities })}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Share({ label, part, total }: { label: string; part: number | null; total: number }) {
  const t = useDictionary();
  if (part === null) {
    return <span className="text-xs text-shell-muted">{t.environment.coverage.notApplicable}</span>;
  }
  const share = total ? Math.round((part / total) * 100) : 0;
  return (
    <span className="flex items-center gap-2">
      <span
        className="h-1.5 w-12 overflow-hidden rounded-full bg-shell-canvas"
        role="meter"
        aria-label={fill(t.environment.coverage.meter, { measure: label, part, total })}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={share}
      >
        <span
          className="block h-full rounded-full bg-state-success"
          style={{ width: `${share}%` }}
        />
      </span>
      <span className="text-brand-navy">{share} %</span>
    </span>
  );
}
