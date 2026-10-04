"use client";

import { Info } from "lucide-react";

import { cn } from "cn";

import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { confidenceLevel, type ConfidenceLevel } from "@/lib/intelligence";

/**
 * How sure LEKA is, and what it does not know (LEKA-341) — always in
 * words, never a colour alone: "Confiance élevée · 90 %", or "Confiance
 * inconnue" when nothing said how sure. What it rests on — a source's word
 * or LEKA's inference — goes with it.
 */

const BARS: Record<ConfidenceLevel, number> = { high: 3, medium: 2, low: 1, unknown: 0 };
const TONE: Record<ConfidenceLevel, string> = {
  high: "bg-state-success",
  medium: "bg-state-warning",
  low: "bg-state-danger",
  unknown: "bg-shell-line",
};

export function ConfidenceBadge({
  score,
  basis,
  className,
}: {
  score: number | null | undefined;
  basis?: "stated" | "inferred" | null;
  className?: string;
}) {
  const t = useDictionary();
  const w = t.intelligence.confidence;
  const level = confidenceLevel(score);
  const said =
    level === "unknown"
      ? w.unknown
      : `${w[level]} · ${Math.round((score ?? 0) * 100)} %`;
  return (
    <span
      className={cn("inline-flex items-center gap-1.5 text-xs text-brand-navy", className)}
      data-level={level}
      data-testid="confidence"
    >
      <span aria-hidden="true" className="flex items-end gap-0.5">
        {[1, 2, 3].map((bar) => (
          <span
            key={bar}
            className={cn(
              "w-1 rounded-sm",
              bar === 1 ? "h-1.5" : bar === 2 ? "h-2.5" : "h-3.5",
              bar <= BARS[level] ? TONE[level] : "bg-shell-line",
            )}
          />
        ))}
      </span>
      <span>
        {said}
        {basis ? <span className="text-shell-muted"> · {w[basis]}</span> : null}
      </span>
    </span>
  );
}

/** What LEKA does not know — said, so a decision is not taken on what it
 * only guessed. Nothing when it knows everything it looked for. */
export function UncertaintyList({ items }: { items: readonly string[] }) {
  const t = useDictionary();
  if (items.length === 0) return null;
  return (
    <section
      aria-label={t.intelligence.uncertainty.title}
      className="rounded-lg bg-shell-canvas p-3 text-[0.8125rem]"
      data-testid="uncertainties"
    >
      <p className="mb-1 flex items-center gap-1.5 font-medium text-brand-navy">
        <Info className="size-4 text-state-info" aria-hidden="true" />
        {fill(t.intelligence.uncertainty.title, { count: items.length })}
      </p>
      <ul className="list-disc space-y-0.5 pl-6 text-shell-muted">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}
