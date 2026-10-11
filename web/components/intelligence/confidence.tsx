"use client";

import { CircleCheck, CircleHelp } from "lucide-react";
import { useId } from "react";

import { cn } from "cn";

import type { TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { IntelligenceSection } from "@/components/intelligence/section";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { confidenceLevel, type ConfidenceLevel, type Support } from "@/lib/intelligence";

/**
 * How sure LEKA is, what that rests on, and what it does not know
 * (LEKA-341) — as mockups 03 to 05 say it: "● Confiance élevée" in a pill,
 * and under "Confiance de l'analyse" the lines it rests on, ticked when
 * established ("12 sources concordantes"), a grey dot when still missing.
 * Always in words, never a colour alone; "Confiance inconnue" when nothing
 * said how sure — never a made-up number.
 */

const TONES: Record<ConfidenceLevel, TileTone> = {
  high: "success",
  medium: "warning",
  low: "danger",
  unknown: "neutral",
};

export function ConfidenceBadge({
  score,
  basis,
  short = false,
  detail = true,
  className,
}: {
  score: number | null | undefined;
  /** A source's word, or LEKA's inference. */
  basis?: "stated" | "inferred" | null;
  /** "Élevée" alone, under a heading that already says "Confiance". */
  short?: boolean;
  /** The score and its basis beside the pill: "83 % · déclaré par la source". */
  detail?: boolean;
  className?: string;
}) {
  const t = useDictionary();
  const w = t.intelligence.confidence;
  const level = confidenceLevel(score);
  const said = [
    level === "unknown" ? null : `${Math.round((score ?? 0) * 100)} %`,
    basis ? w[basis] : null,
  ].filter(Boolean);
  return (
    <span
      className={cn("inline-flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs", className)}
      data-level={level}
      data-testid="confidence"
    >
      <Pill tone={TONES[level]} dot>
        {short ? w.levels[level] : w[level]}
      </Pill>
      {detail && said.length > 0 ? (
        <span className="text-shell-muted">{said.join(" · ")}</span>
      ) : null}
    </span>
  );
}

/** The lines a confidence rests on: ticked when established, a grey dot
 * when still missing. Nothing when there are none. */
export function SupportList({ items }: { items: readonly Support[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="space-y-1.5 text-[0.8125rem]" data-testid="support">
      {items.map((item) => (
        <li key={item.id} className="flex items-start gap-2" data-established={item.established}>
          {item.established ? (
            <CircleCheck className="mt-0.5 size-4 shrink-0 text-state-success" aria-hidden="true" />
          ) : (
            <span
              aria-hidden="true"
              className="mt-1 ms-0.5 size-3 shrink-0 rounded-full bg-shell-line"
            />
          )}
          <span className={item.established ? "text-brand-navy" : "text-shell-muted"}>
            {item.label}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Mockup 05's "Confiance de l'analyse": how sure, and on what. */
export function ConfidencePanel({
  score,
  support = [],
  level = 3,
}: {
  score: number | null | undefined;
  support?: readonly Support[];
  level?: 2 | 3;
}) {
  const t = useDictionary();
  const w = t.intelligence.confidence;
  return (
    <IntelligenceSection
      kind="confidence"
      title={w.title}
      level={level}
      // The pill alone beside the title, which a side column cannot spare
      // the room for more; the score under it.
      action={<ConfidenceBadge score={score} short detail={false} />}
    >
      {confidenceLevel(score) === "unknown" ? null : (
        <p className="-mt-1.5 mb-3 text-xs text-shell-muted" data-testid="confidence-score">
          {fill(w.score, { score: Math.round((score ?? 0) * 100) })}
        </p>
      )}
      {support.length > 0 ? (
        <SupportList items={support} />
      ) : (
        <p className="text-[0.8125rem] text-shell-muted">{w.noSupport}</p>
      )}
    </IntelligenceSection>
  );
}

/** What LEKA does not know — said, so a decision is not taken on what it
 * only guessed. Nothing when it knows everything it looked for. */
export function UncertaintyList({ items }: { items: readonly string[] }) {
  const t = useDictionary();
  const id = useId();
  if (items.length === 0) return null;
  return (
    <section
      aria-labelledby={id}
      className="rounded-xl border border-dashed border-shell-line bg-shell-canvas/60 p-4 text-[0.8125rem]"
      data-testid="uncertainties"
    >
      <p id={id} className="mb-2 flex items-center gap-2 font-semibold text-brand-navy">
        <CircleHelp className="size-4 text-state-info" aria-hidden="true" />
        {fill(t.intelligence.uncertainty.title, { count: items.length })}
      </p>
      <ul className="space-y-1.5 text-shell-muted">
        {items.map((item) => (
          <li key={item} className="flex items-start gap-2">
            <span
              aria-hidden="true"
              className="mt-1.5 size-1.5 shrink-0 rounded-full bg-state-info"
            />
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}
