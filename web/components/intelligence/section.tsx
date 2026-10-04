"use client";

import {
  CircleHelp,
  FileSearch,
  Layers,
  type LucideIcon,
  ScrollText,
  Sparkles,
} from "lucide-react";

import { cn } from "cn";

import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * A part of an intelligence output, and what kind of statement it holds
 * (LEKA-341). The kind is drawn, not only named: a fact sits in a plain
 * card, a hypothesis in an amber one, a proposal in a dashed violet one —
 * so that what LEKA proposes can never be read as what a source says.
 * docs/frontend/intelligence-components.md.
 */

export type SectionKind = "fact" | "hypothesis" | "proposal" | "evidence" | "context";

const LOOK: Record<SectionKind, { icon: LucideIcon; box: string; tag: string }> = {
  fact: {
    icon: ScrollText,
    box: "border border-shell-line bg-white",
    tag: "bg-shell-canvas text-brand-navy",
  },
  hypothesis: {
    icon: CircleHelp,
    box: "border border-state-warning/40 bg-white",
    tag: "bg-state-warning-soft text-state-warning",
  },
  proposal: {
    icon: Sparkles,
    box: "border-2 border-dashed border-brand-violet/50 bg-brand-violet-soft/30",
    tag: "bg-brand-violet-soft text-shell-nav-active",
  },
  evidence: {
    icon: FileSearch,
    box: "border border-shell-line bg-white",
    tag: "bg-shell-canvas text-shell-muted",
  },
  context: {
    icon: Layers,
    box: "border border-shell-line bg-white",
    tag: "bg-shell-canvas text-shell-muted",
  },
};

export function IntelligenceSection({
  kind,
  title,
  action,
  level = 3,
  className,
  children,
}: {
  kind: SectionKind;
  title: string;
  /** Its heading's level: the screen's next one — 2 under the page's title. */
  level?: 2 | 3;
  action?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  const t = useDictionary();
  const look = LOOK[kind];
  const Icon = look.icon;
  const Heading = level === 2 ? "h2" : "h3";
  const id = `intelligence-${kind}-${title.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <section
      aria-labelledby={id}
      data-kind={kind}
      data-testid={`intelligence-${kind}`}
      className={cn("rounded-xl p-4", look.box, className)}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
            look.tag,
          )}
        >
          <Icon className="size-3.5" aria-hidden="true" />
          {t.intelligence.kinds[kind]}
        </span>
        <Heading id={id} className="flex-1 text-[0.9375rem] font-semibold text-brand-navy">
          {title}
        </Heading>
        {action}
      </div>
      {children}
    </section>
  );
}
