"use client";

import {
  CircleAlert,
  CircleDashed,
  CircleHelp,
  CircleX,
  LoaderCircle,
  type LucideIcon,
} from "lucide-react";

import { cn } from "cn";

import { Button } from "@/components/ui/button";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { AnalysisStatus } from "@/lib/intelligence";

/**
 * How an analysis went, said before what it found (LEKA-341): running —
 * mockup 03's "Analyse en cours…", what it found so far shown under it;
 * partial — and what is missing; inconclusive — LEKA looked and cannot
 * say; failed — it could not run, and a way to try again; pending — none
 * yet. A complete analysis needs no banner: its sections speak.
 */

const LOOK: Record<Exclude<AnalysisStatus, "complete">, { icon: LucideIcon; tone: string }> = {
  running: { icon: LoaderCircle, tone: "bg-brand-violet-soft/60 text-shell-nav-active" },
  partial: { icon: CircleAlert, tone: "bg-state-warning-soft text-state-warning" },
  inconclusive: { icon: CircleHelp, tone: "bg-state-info-soft text-state-info" },
  failed: { icon: CircleX, tone: "bg-state-danger-soft text-state-danger" },
  pending: { icon: CircleDashed, tone: "bg-shell-canvas text-shell-muted" },
};

export function AnalysisState({
  status,
  missing = [],
  onRetry,
}: {
  status: AnalysisStatus;
  missing?: readonly string[];
  onRetry?: () => void;
}) {
  const t = useDictionary();
  if (status === "complete") return null;
  const w = t.intelligence.status[status];
  const { icon: Icon, tone } = LOOK[status];
  return (
    <div
      role={status === "failed" ? "alert" : "status"}
      className={cn("flex flex-wrap items-start gap-3 rounded-xl px-4 py-3 text-[0.8125rem]", tone)}
      data-testid="analysis-state"
      data-status={status}
    >
      <Icon
        className={cn("mt-0.5 size-4 shrink-0", status === "running" && "motion-safe:animate-spin")}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1 text-brand-navy">
        <p className="font-semibold">{w.title}</p>
        <p className="text-shell-muted">{w.body}</p>
        {missing.length > 0 ? (
          <ul className="mt-1 list-disc pl-5 text-shell-muted">
            {missing.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : null}
      </div>
      {status === "failed" && onRetry ? (
        <Button size="sm" variant="outline" onClick={onRetry}>
          {t.intelligence.status.failed.retry}
        </Button>
      ) : null}
    </div>
  );
}
