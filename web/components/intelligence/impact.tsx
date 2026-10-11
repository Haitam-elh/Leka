"use client";

import { Activity, ChevronRight, ShieldAlert } from "lucide-react";
import Link from "next/link";

import { cn } from "cn";

import { IconTile, type TileTone, typeIcon } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Impact, RiskLevel } from "@/lib/intelligence";

/**
 * What a situation reaches, and how bad that is (LEKA-341), as mockup 05
 * draws it under "Impact global" (its section's title): "Élevé", what it
 * is read from and how many things it concerns; then area by area — what
 * is touched, what depends on it, the applications, the business — a line
 * per thing, to its sheet. An impact nothing said is "Inconnu", never low.
 */

export const RISK_TONES: Record<RiskLevel, TileTone> = {
  high: "danger",
  medium: "warning",
  low: "success",
  unknown: "neutral",
};

const LEVEL_TEXT: Record<RiskLevel, string> = {
  high: "text-state-danger",
  medium: "text-state-warning",
  low: "text-state-success",
  unknown: "text-shell-muted",
};

/** A risk in a pill, where there is no room for the panel. */
export function RiskBadge({ level, basis }: { level: RiskLevel; basis?: string | null }) {
  const t = useDictionary();
  return (
    <Pill tone={RISK_TONES[level]} data-level={level} data-testid="risk" title={basis ?? undefined}>
      <ShieldAlert className="size-3.5" aria-hidden="true" />
      {t.intelligence.risk[level]}
    </Pill>
  );
}

export function ImpactPanel({ impact }: { impact: Impact | null }) {
  const t = useDictionary();
  const w = t.intelligence.impact;
  if (impact === null) {
    return <p className="text-[0.8125rem] text-shell-muted">{w.none}</p>;
  }
  const areas = impact.areas.filter((area) => area.items.length > 0);
  const concerned = new Set(areas.flatMap((area) => area.items.map((item) => item.id))).size;
  return (
    <div className="space-y-4 text-[0.8125rem]" data-testid="impact">
      <div className="flex items-start gap-3">
        <IconTile icon={Activity} tone={RISK_TONES[impact.risk]} className="size-11" />
        <div className="min-w-0 flex-1">
          <p
            className={cn("text-2xl leading-tight font-semibold", LEVEL_TEXT[impact.risk])}
            data-level={impact.risk}
            data-testid="impact-level"
          >
            {w.levels[impact.risk]}
          </p>
          <p className="text-xs text-shell-muted">
            {concerned > 0 ? `${fill(w.concerned, { count: concerned })} · ` : null}
            {impact.riskBasis}
          </p>
        </div>
      </div>
      {areas.length === 0 ? (
        <p className="text-shell-muted">{w.none}</p>
      ) : (
        areas.map((area) => (
          <div key={area.id}>
            <p className="mb-1 flex items-center justify-between gap-2 font-semibold text-brand-navy">
              {area.label}
              <span className="text-xs font-medium text-shell-nav-active">
                {fill(w.count, { count: area.items.length })}
              </span>
            </p>
            <ul className="divide-y divide-shell-line/60" aria-label={area.label}>
              {area.items.map((item) => {
                const body = (
                  <>
                    <IconTile
                      icon={typeIcon(item.type ?? "")}
                      tone="violet"
                      className="size-8 [&>svg]:size-4"
                    />
                    <span className="min-w-0 flex-1 truncate font-medium text-brand-navy">
                      {item.label}
                    </span>
                    {item.detail ? (
                      <span className="shrink-0 text-xs text-shell-muted">{item.detail}</span>
                    ) : null}
                  </>
                );
                return (
                  <li key={item.id}>
                    {item.href ? (
                      <Link
                        href={item.href}
                        className="flex items-center gap-3 rounded-lg px-1 py-1.5 outline-none hover:bg-shell-canvas focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                      >
                        {body}
                        <ChevronRight className="rtl:-scale-x-100 size-4 shrink-0 text-shell-muted" aria-hidden="true" />
                      </Link>
                    ) : (
                      <span className="flex items-center gap-3 px-1 py-1.5">{body}</span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        ))
      )}
    </div>
  );
}
