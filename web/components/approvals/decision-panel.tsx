"use client";

import { ArrowRight, X, Zap } from "lucide-react";
import Link from "next/link";

import { wordDecision } from "@/components/approvals/items";
import { DecisionCard } from "@/components/decisions/decision-card";
import { timeAgo } from "@/components/knowledge/time";
import { useCurrentUser } from "@/components/shell/shell-provider";
import { routes } from "@/config/routes";
import type { DecisionItem } from "@/lib/decisions";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * A decision beside À valider's list (LEKA-390), as mockup 09's panel:
 * what it would do, who asked and when, what the analysis concluded — and
 * the decision itself, to approve, reject, modify or send back.
 */
export function DecisionPanel({ item, onClose }: { item: DecisionItem; onClose: () => void }) {
  const t = useDictionary();
  const me = useCurrentUser();
  const { title, why } = wordDecision(t, item);
  const { intention, decision } = item;
  const asked = intention.created_by && intention.created_by === me?.id;
  return (
    <aside
      aria-label={fill(t.approvals.conflict.panel.label, { title })}
      data-testid="decision-panel"
      className="flex flex-col gap-4 self-start rounded-xl border border-shell-line bg-white p-4 xl:sticky xl:top-4"
    >
      <header className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-violet-soft text-shell-nav-active">
          <Zap className="size-5" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base leading-snug font-semibold text-brand-navy">{title}</h2>
          {why ? <p className="text-sm text-shell-muted">{why}</p> : null}
          <p className="mt-1 text-xs text-shell-muted">
            {asked ? t.decisions.requestedBy.you : t.decisions.requestedBy.someone} ·{" "}
            {timeAgo(t, decision.created_at)}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t.approvals.panel.close}
          className="rounded p-1 text-shell-muted outline-none hover:text-brand-navy focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </header>
      <div className="rounded-lg bg-shell-highlight px-3 py-2 text-[0.8125rem]">
        <p className="font-medium text-brand-navy">{intention.title}</p>
        <Link
          href={routes.intention(intention.id, "analysis")}
          className="mt-1 inline-flex items-center gap-1 font-medium text-shell-nav-active hover:underline"
        >
          {t.decisions.see}
          <ArrowRight className="rtl:-scale-x-100 size-3.5" aria-hidden="true" />
        </Link>
      </div>
      <DecisionCard decision={decision} />
    </aside>
  );
}
