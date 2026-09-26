"use client";

import { TriangleAlert } from "lucide-react";

import { cn } from "cn";

import { hoursSince, exactDate, timeAgo } from "@/components/knowledge/time";
import { SourceLogo, sourceTitle } from "@/components/sources/source-logo";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { Provenance } from "@/lib/knowledge";

export interface ProvenanceBadgeProps {
  source: Provenance;
  /** Overrides source.syncedAt, for a record synced apart from its source. */
  syncedAt?: string | null;
  /** 0 to 100, shown in the tooltip. */
  quality?: number;
  /** The source's name next to its logo. The logo alone when false. */
  showLabel?: boolean;
  /** Past this, the badge turns orange and says the data is old. 24 h by default. */
  staleAfterHours?: number;
  className?: string;
}

/**
 * Where a piece of knowledge came from (LEKA-340): the source's logo and
 * name; in the tooltip, the full source, when it was last synced, and its
 * quality. Past `staleAfterHours` it turns orange with a warning icon — the
 * data may no longer be true, and that is worth seeing before trusting it.
 *
 * A focusable button, so the tooltip opens from the keyboard too; its
 * accessible name carries everything the tooltip shows.
 */
export function ProvenanceBadge({
  source,
  syncedAt,
  quality,
  showLabel = true,
  staleAfterHours = 24,
  className,
}: ProvenanceBadgeProps) {
  const t = useDictionary();
  const { locale } = useLocale();
  const synced = syncedAt !== undefined ? syncedAt : (source.syncedAt ?? null);
  const stale = synced !== null && hoursSince(synced) >= staleAfterHours;

  const title = sourceTitle(source.kind);
  const full = source.name ? `${title} · ${source.name}` : title;
  const lines = [
    full,
    synced
      ? `${fill(t.knowledge.provenance.syncedAt, { date: exactDate(locale, synced) })} (${timeAgo(t, synced)})`
      : t.knowledge.provenance.never,
    ...(quality !== undefined
      ? [fill(t.knowledge.provenance.quality, { score: Math.round(quality) })]
      : []),
    ...(stale ? [t.knowledge.provenance.stale] : []),
  ];

  return (
    <Tooltip>
      {/* Its name says how long ago it synced — computed from now. */}
      <TooltipTrigger
        suppressHydrationWarning
        data-stale={stale ? "true" : undefined}
        aria-label={`${fill(t.knowledge.provenance.aria, { source: full })}. ${lines.slice(1).join(". ")}`}
        className={cn(
          "inline-flex w-fit max-w-full items-center gap-1.5 rounded-md border px-1.5 py-0.5 text-xs font-medium outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
          stale
            ? "border-transparent bg-state-warning-soft text-state-warning"
            : "border-shell-line bg-white text-shell-nav",
          className,
        )}
      >
        <SourceLogo kind={source.kind} className="size-3.5 shrink-0" />
        {showLabel ? <span className="truncate">{source.name ?? title}</span> : null}
        {stale ? <TriangleAlert aria-hidden="true" className="size-3.5 shrink-0" /> : null}
      </TooltipTrigger>
      <TooltipContent>
        <span className="flex flex-col gap-0.5">
          {lines.map((line) => (
            <span key={line}>{line}</span>
          ))}
        </span>
      </TooltipContent>
    </Tooltip>
  );
}
