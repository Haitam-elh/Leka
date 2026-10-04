"use client";

import { ArrowRight, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { entityHref, IconTile, typeLabel } from "@/components/environment/parts";
import { AnalysisView } from "@/components/intelligence";
import { routes } from "@/config/routes";
import { incidentAnalysis } from "@/lib/incident-analysis";
import { useIncident } from "@/lib/incident-queries";
import { useSources } from "@/lib/sources-queries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Analysis } from "@/lib/intelligence";

/**
 * An incident's sheet, its "Analyse de LEKA" (LEKA-341): what the company
 * model knows of the incident — its state, what it touches, what is said
 * or suspected to have caused it and what changed just before, what it
 * reaches — drawn with the intelligence components. Real, or said to be
 * missing; never invented. A failed read says so, and offers to retry.
 */
export function IncidentAnalysis({ id }: { id: string }) {
  const t = useDictionary();
  const w = t.environment.sheet.analysis;
  const incident = useIncident(id);
  // What names the records' sources: the workspace's, by id.
  const sources = useSources();
  const analysis = useMemo<Analysis | null>(() => {
    if (incident.isError) {
      return {
        status: "failed",
        missing: [],
        findings: [],
        causes: [],
        impact: null,
        recommendations: [],
        uncertainties: [],
        confidence: null,
      };
    }
    if (!incident.data) return null;
    const named = new Map((sources.data ?? []).map((s) => [s.id, s]));
    return incidentAnalysis(incident.data, t, {
      href: entityHref,
      typeName: (type) => typeLabel(t, type),
      source: (sourceId) => {
        const found = named.get(sourceId);
        return found ? { kind: found.type, name: found.display_name } : null;
      },
    });
  }, [incident.data, incident.isError, sources.data, t]);

  return (
    <section
      aria-labelledby="incident-analysis"
      className="flex flex-col gap-4 rounded-xl bg-shell-highlight px-6 py-5"
      data-testid="incident-analysis"
    >
      <div className="flex flex-wrap items-center gap-4">
        <IconTile icon={ShieldCheck} tone="violet" className="size-11" />
        <div className="min-w-0 flex-1">
          <h2 id="incident-analysis" className="text-[1.0625rem] font-semibold text-brand-navy">
            {w.title}
          </h2>
          <p className="text-[0.8125rem] text-shell-muted">{w.incident}</p>
        </div>
        <Link
          href={routes.intentionNew()}
          className="flex items-center gap-2 rounded-lg border border-brand-navy/20 bg-white px-4 py-2 text-sm font-medium text-brand-navy outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        >
          {w.action}
          <ArrowRight className="size-4" aria-hidden="true" />
        </Link>
      </div>
      {analysis ? (
        <AnalysisView analysis={analysis} onRetry={() => void incident.refetch()} />
      ) : (
        <div className="h-48 animate-pulse rounded-lg bg-white/60" aria-hidden="true" />
      )}
    </section>
  );
}
