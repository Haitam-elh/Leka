"use client";

import { ChevronDown, ShieldCheck } from "lucide-react";
import { useId, useMemo, useState } from "react";

import { cn } from "cn";

import { entityHref, IconTile, typeLabel } from "@/components/environment/parts";
import { AnalysisState, AnalysisView } from "@/components/intelligence";
import { incidentAnalysis } from "@/lib/incident-analysis";
import { useIncident } from "@/lib/incident-queries";
import { useSources } from "@/lib/sources-queries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Analysis } from "@/lib/intelligence";

/**
 * An incident's sheet, its "Analyse de LEKA" (LEKA-341), as mockup 11's
 * band: what it comes to in a few sentences, and "Voir l'analyse complète"
 * opening it in place — laid out as mockup 04, with the intelligence
 * components: what its sources say, what is said or suspected to have
 * caused it and what changed just before, the evidence, what it reaches,
 * how sure and on what, what is not known. Real, or said to be missing;
 * never invented. A failed read says so without being opened, and offers
 * to retry.
 */
export function IncidentAnalysis({ id }: { id: string }) {
  const t = useDictionary();
  const w = t.environment.sheet.analysis;
  const incident = useIncident(id);
  // What names the records' sources: the workspace's, by id.
  const sources = useSources();
  const [open, setOpen] = useState(false);
  const detail = useId();
  const analysis = useMemo<Analysis | null>(() => {
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
  }, [incident.data, sources.data, t]);

  return (
    <section
      aria-labelledby="incident-analysis"
      className="flex flex-col gap-4 rounded-xl bg-shell-highlight px-6 py-5"
      data-testid="incident-analysis"
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
        <IconTile icon={ShieldCheck} tone="violet" className="size-11" />
        <div className="min-w-0 flex-1">
          <h2 id="incident-analysis" className="text-[1.0625rem] font-semibold text-brand-navy">
            {w.title}
          </h2>
          {analysis ? (
            <p className="text-[0.8125rem] text-shell-muted" data-testid="incident-summary">
              {analysis.summary}
            </p>
          ) : incident.isError ? null : (
            <p className="text-[0.8125rem] text-shell-muted">{w.incident}</p>
          )}
        </div>
        {analysis ? (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={open ? detail : undefined}
            onClick={() => setOpen(!open)}
            className="flex shrink-0 items-center gap-2 self-start rounded-lg border border-brand-navy/20 bg-white px-4 py-2 text-sm font-medium text-brand-navy outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40 lg:self-center"
          >
            {open ? w.hide : w.full}
            <ChevronDown
              className={cn("size-4 transition-transform", open && "rotate-180")}
              aria-hidden="true"
            />
          </button>
        ) : null}
      </div>
      {incident.isError ? (
        <AnalysisState status="failed" onRetry={() => void incident.refetch()} />
      ) : !analysis ? (
        <div className="h-5 w-2/3 animate-pulse rounded bg-white/60" aria-hidden="true" />
      ) : open ? (
        <div id={detail}>
          <AnalysisView analysis={analysis} synthesis={false} />
        </div>
      ) : (
        <AnalysisState status={analysis.status} missing={analysis.missing} />
      )}
    </section>
  );
}
