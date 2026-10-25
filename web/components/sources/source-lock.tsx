"use client";

import { Lock } from "lucide-react";
import Link from "next/link";

import { cn } from "cn";
import { buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { useCredits } from "@/lib/billing-queries";
import { ENTERPRISE } from "@/lib/contract";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { isConnected } from "@/lib/sources";
import { useSources } from "@/lib/sources-queries";

/**
 * Locked until a source is connected (2026-10-25: under a contract, a
 * question was asked with nothing connected). An Enterprise organisation's
 * questions and « Mon environnement » wait for its first source: LEKA
 * answers from its documentation, and with nothing to read an answer would
 * be invented. The server refuses the question too (`source_required`).
 *
 * A public plan keeps its demonstration and its first steps: never locked.
 * Locked only once known — the plan and the sources read —, never assumed.
 */
export function useSourceLock(): boolean {
  const plan = useCredits().data?.plan;
  const sources = useSources().data;
  return plan === ENTERPRISE && sources !== undefined && !sources.some(isConnected);
}

export function SourceLocked({
  what,
  compact = false,
}: {
  what: "ask" | "environment";
  compact?: boolean;
}) {
  const t = useDictionary();
  const w = t.sourceLock;
  return (
    <section
      className={cn(
        "relative overflow-hidden rounded-2xl border border-brand-violet/25 bg-white text-center",
        compact ? "px-5 py-6" : "px-6 py-14",
      )}
      aria-labelledby={`source-lock-${what}`}
      data-testid="source-lock"
      data-what={what}
    >
      {/* A soft violet wash behind the padlock, nothing to read in it. */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-brand-violet-soft/70 to-transparent"
        aria-hidden="true"
      />
      <div className="relative">
        <span className="mx-auto flex size-12 items-center justify-center rounded-2xl bg-white text-shell-nav-active shadow-sm ring-1 ring-brand-violet/25">
          <Lock className="size-5" aria-hidden="true" />
          <span className="sr-only">{w.locked}</span>
        </span>
        <h2
          id={`source-lock-${what}`}
          className="mt-3 text-[1.0625rem] font-semibold text-balance text-brand-navy"
        >
          {w.title[what]}
        </h2>
        <p className="mx-auto mt-1 max-w-md text-sm text-shell-muted">{w.body}</p>
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          <Link
            href={`${routes.sources()}?connect=confluence`}
            className={buttonVariants({ size: "sm" })}
            data-testid="source-lock-connect"
          >
            {w.connect}
          </Link>
          <Link
            href={routes.welcome()}
            className={buttonVariants({ size: "sm", variant: "outline" })}
            data-testid="source-lock-other"
          >
            {w.other}
          </Link>
        </div>
      </div>
    </section>
  );
}
