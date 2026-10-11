"use client";

import { StatusBadge } from "@/components/knowledge/status-badge";
import { timeAgo } from "@/components/knowledge/time";
import { SourceLogo } from "@/components/sources/source-logo";
import { useDictionary } from "@/lib/i18n/locale-provider";
import {
  lastSeen,
  type Source,
  type SourceKind,
  type SourceTone,
  sourceTone,
} from "@/lib/sources";

const SEVERITY: Record<SourceTone, number> = {
  error: 0,
  attention: 1,
  synced: 2,
  setup: 3,
  off: 4,
};

/** One line of the list: a source, or an example's. */
export interface SourceLine {
  id: string;
  kind: SourceKind;
  name: string;
  tone: SourceTone;
  /** ISO 8601, or null for never. */
  seen: string | null;
}

export function sourceLines(sources: readonly Source[]): SourceLine[] {
  return sources.map((source) => ({
    id: source.id,
    kind: source.type,
    name: source.display_name,
    tone: sourceTone(source),
    seen: lastSeen(source),
  }));
}

/**
 * Sources in a few lines — logo, name, state, when last heard from — as
 * mockups 01 and 10 draw them: what needs a look first, then the rest,
 * most recently heard from first.
 */
export function SourceLines({ lines, max }: { lines: readonly SourceLine[]; max: number }) {
  const t = useDictionary();
  const shown = [...lines]
    .sort(
      (a, b) =>
        SEVERITY[a.tone] - SEVERITY[b.tone] ||
        Date.parse(b.seen ?? "1970") - Date.parse(a.seen ?? "1970"),
    )
    .slice(0, max);

  return (
    <ul className="space-y-1">
      {shown.map((line) => (
        // Its name has the width to be read; when it was last seen, under it.
        <li key={line.id} className="flex items-center gap-3 py-1.5" data-testid="source-row">
          <SourceLogo kind={line.kind} className="size-5 shrink-0" />
          <span className="min-w-0 flex-1">
            <span
              title={line.name}
              className="block truncate text-[0.8125rem] font-medium text-brand-navy"
            >
              {line.name}
            </span>
            <span className="block text-xs whitespace-nowrap text-shell-muted">
              {line.seen ? timeAgo(t, line.seen) : t.overview.neverSeen}
            </span>
          </span>
          <StatusBadge variant={`source.${line.tone}`} />
        </li>
      ))}
    </ul>
  );
}

/** The workspace's own sources, as lines. */
export function ConnectedSources({ sources, max }: { sources: readonly Source[]; max: number }) {
  return <SourceLines lines={sourceLines(sources)} max={max} />;
}
