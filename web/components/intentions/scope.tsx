"use client";

import { Crosshair } from "lucide-react";

import { Card } from "@/components/environment/parts";
import { exactDate } from "@/components/knowledge/time";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { IntentionDetail } from "@/lib/intentions/api";

/**
 * The scope an intention was asked with (LEKA-386): its environment, its
 * period, the services and sources chosen — as the overview lists it, and
 * as mockup 03's "Périmètre de l'analyse" lays it out beside the analysis.
 * Nothing chosen is said so: the analysis then reads the request's words.
 */

type Dictionary = ReturnType<typeof useDictionary>;

/** One line each: "Environnement · production". */
export function scopeLines(t: Dictionary, locale: string, scope: Record<string, unknown>): string[] {
  const w = t.intentions.overview;
  const lines: string[] = [];
  if (typeof scope.environment === "string") {
    lines.push(`${w.environment} · ${scope.environment}`);
  }
  if (typeof scope.since === "string") {
    const since = exactDate(locale, scope.since);
    const until = typeof scope.until === "string" ? ` → ${exactDate(locale, scope.until)}` : "";
    lines.push(`${w.period} · ${since}${until}`);
  }
  if (Array.isArray(scope.services) && scope.services.length) {
    lines.push(fill(w.services, { count: scope.services.length }));
  }
  if (Array.isArray(scope.sources) && scope.sources.length) {
    lines.push(fill(w.sources, { count: scope.sources.length }));
  }
  return lines;
}

/** Mockup 03's "Périmètre de l'analyse": each part of the scope, by name. */
export function ScopeCard({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.intentions.overview;
  const a = t.intentions.analysis;
  const scope = intention.scope as Record<string, unknown>;
  const period =
    typeof scope.since === "string"
      ? `${exactDate(locale, scope.since)}${typeof scope.until === "string" ? ` → ${exactDate(locale, scope.until)}` : ""}`
      : a.scopeDefault;
  const rows: [string, string][] = [
    [w.environment, typeof scope.environment === "string" ? scope.environment : a.scopeAll],
    [w.period, period],
  ];
  if (Array.isArray(scope.services) && scope.services.length) {
    rows.push([a.scopeServices, fill(w.services, { count: scope.services.length })]);
  }
  if (Array.isArray(scope.sources) && scope.sources.length) {
    rows.push([a.scopeSources, fill(w.sources, { count: scope.sources.length })]);
  }
  return (
    <Card
      title={a.scopeTitle}
      icon={<Crosshair className="size-4 text-shell-muted" aria-hidden="true" />}
    >
      <dl
        className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-3 gap-y-2 text-[0.8125rem]"
        data-testid="analysis-scope"
      >
        {rows.map(([label, value], index) => (
          <div key={index} className="contents">
            <dt className="text-shell-muted">{label}</dt>
            <dd className="font-medium text-brand-navy" dir="auto">
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}
