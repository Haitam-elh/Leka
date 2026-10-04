"use client";

import {
  CircleHelp,
  FileSearch,
  Gauge,
  Info,
  Layers,
  type LucideIcon,
  Radar,
  Sparkles,
} from "lucide-react";
import { useId } from "react";

import { cn } from "cn";

/**
 * A part of an intelligence output (LEKA-341), drawn as mockups 03 to 05
 * draw theirs — "Premiers constats", "Preuves et sources clés",
 * "Recommandations de LEKA": a card, its icon, its title, how many, and
 * what it holds in data-kind. What kind of statement each line is, the
 * line says: a fact is tagged "Constat", a hypothesis "Cause probable" or
 * "À confirmer" with how sure, a proposal is a card with its priority and
 * a box to tick — so what LEKA proposes is never read as what a source
 * says. docs/frontend/intelligence-components.md.
 */

export type SectionKind =
  | "fact"
  | "hypothesis"
  | "proposal"
  | "evidence"
  | "impact"
  | "confidence"
  | "context";

const ICONS: Record<SectionKind, { icon: LucideIcon; tone: string }> = {
  fact: { icon: Info, tone: "text-shell-nav-active" },
  hypothesis: { icon: CircleHelp, tone: "text-state-warning" },
  proposal: { icon: Sparkles, tone: "text-shell-nav-active" },
  evidence: { icon: FileSearch, tone: "text-shell-nav-active" },
  impact: { icon: Radar, tone: "text-state-danger" },
  confidence: { icon: Gauge, tone: "text-shell-nav-active" },
  context: { icon: Layers, tone: "text-shell-nav-active" },
};

export function IntelligenceSection({
  kind,
  title,
  subtitle,
  count,
  action,
  level = 3,
  className,
  children,
}: {
  kind: SectionKind;
  title: string;
  /** What to do with it, under the title: "Sélectionnez les actions…". */
  subtitle?: string;
  /** How many, beside the title: "3 recommandations". */
  count?: string;
  /** Its heading's level: the screen's next one — 2 under the page's title. */
  level?: 2 | 3;
  action?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  const { icon: Icon, tone } = ICONS[kind];
  const Heading = level === 2 ? "h2" : "h3";
  const id = useId();
  return (
    <section
      aria-labelledby={id}
      data-kind={kind}
      data-testid={`intelligence-${kind}`}
      className={cn("min-w-0 rounded-xl border border-shell-line bg-white p-4", className)}
    >
      <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1">
        <Icon className={cn("size-5 shrink-0", tone)} aria-hidden="true" />
        <Heading
          id={id}
          className="min-w-0 flex-1 text-[1.0625rem] font-semibold tracking-[-0.01em] text-brand-navy"
        >
          {title}
        </Heading>
        {count ? (
          <span className="text-[0.8125rem] font-medium text-shell-nav-active">{count}</span>
        ) : null}
        {action}
      </div>
      {subtitle ? <p className="-mt-1.5 mb-3 text-[0.8125rem] text-shell-muted">{subtitle}</p> : null}
      {children}
    </section>
  );
}
