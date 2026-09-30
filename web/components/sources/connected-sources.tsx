"use client";

import { StatusBadge } from "@/components/knowledge/status-badge";
import { timeAgo } from "@/components/knowledge/time";
import { SourceLogo } from "@/components/sources/source-logo";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { lastSeen, type Source, type SourceTone, sourceTone } from "@/lib/sources";

const SEVERITY: Record<SourceTone, number> = {
  error: 0,
  attention: 1,
  synced: 2,
  setup: 3,
  off: 4,
};

/**
 * The workspace's sources in a few lines — logo, name, state, when last
 * heard from — as mockups 01 and 10 draw them: what needs a look first,
 * then the rest, most recently heard from first.
 */
export function ConnectedSources({ sources, max }: { sources: readonly Source[]; max: number }) {
  const t = useDictionary();
  const shown = [...sources]
    .sort(
      (a, b) =>
        SEVERITY[sourceTone(a)] - SEVERITY[sourceTone(b)] ||
        Date.parse(lastSeen(b) ?? "1970") - Date.parse(lastSeen(a) ?? "1970"),
    )
    .slice(0, max);

  return (
    <ul className="space-y-1">
      {shown.map((source) => {
        const seen = lastSeen(source);
        return (
          <li key={source.id} className="flex items-center gap-3 py-1.5" data-testid="source-row">
            <SourceLogo kind={source.type} className="size-5 shrink-0" />
            <span
              title={source.display_name}
              className="min-w-0 flex-1 truncate text-[0.8125rem] font-medium text-brand-navy"
            >
              {source.display_name}
            </span>
            <StatusBadge variant={`source.${sourceTone(source)}`} />
            <span className="shrink-0 text-right text-xs whitespace-nowrap text-shell-muted">
              {seen ? timeAgo(t, seen) : t.overview.neverSeen}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
