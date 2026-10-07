"use client";

import { ChevronRight, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { cn } from "cn";

import type { TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { timeAgo } from "@/components/knowledge/time";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { ErrorState } from "@/components/states/error-state";
import { buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { routes } from "@/config/routes";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Intention, IntentionPhase, IntentionStatus } from "@/lib/intentions/api";
import { useIntentionCounts, useIntentions } from "@/lib/intentions/queries";

/**
 * Mes intentions (LEKA-384, mockup 07): what was asked of LEKA, the latest
 * changed first, by phase — in progress, finished, scheduled, archived —
 * each with where it stands and when it last moved, leading to its page.
 *
 * Every row is a kept intention (GET /intentions); the counts are the
 * API's. The mockup's impact and sources columns come with the analysis
 * (LEKA-388, 389): not drawn before there is something to put in them.
 */

type Dictionary = ReturnType<typeof useDictionary>;

export const STATUS_TONES: Record<IntentionStatus, TileTone> = {
  submitted: "neutral",
  analysing: "violet",
  awaiting_decision: "warning",
  approved: "violet",
  scheduled: "violet",
  executing: "info",
  verifying: "info",
  completed: "success",
  rejected: "neutral",
  failed: "danger",
  cancelled: "neutral",
};

const TABS = [null, "active", "finished", "scheduled", "archived"] as const;

export function StatusPill({ status }: { status: IntentionStatus }) {
  const t = useDictionary();
  return (
    <Pill tone={STATUS_TONES[status]} dot data-testid="intention-status" data-status={status}>
      {t.intentions.statuses[status]}
    </Pill>
  );
}

export function kindOf(t: Dictionary, kind: string | null): string | null {
  return kind ? ((t.intent.kinds as Record<string, string>)[kind] ?? kind) : null;
}

function Row({ intention }: { intention: Intention }) {
  const t = useDictionary();
  const kind = kindOf(t, intention.kind);
  return (
    <li data-testid="intention-row">
      <Link
        href={routes.intention(intention.id)}
        className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 px-4 py-3 outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-brand-violet/40 md:grid-cols-[minmax(0,1fr)_10rem_10rem_1rem]"
      >
        <span className="min-w-0">
          <span className="block truncate text-[0.9375rem] font-semibold text-brand-navy">
            {intention.title}
          </span>
          {kind ? <span className="block text-[0.8125rem] text-shell-muted">{kind}</span> : null}
        </span>
        <span>
          <StatusPill status={intention.status} />
        </span>
        <span className="col-span-2 text-[0.8125rem] text-shell-muted md:col-span-1">
          {timeAgo(t, intention.updated_at)}
        </span>
        <ChevronRight className="hidden size-4 text-shell-muted md:block" aria-hidden="true" />
      </Link>
    </li>
  );
}

export function IntentionsList() {
  const t = useDictionary();
  const w = t.intentions;
  const [phase, setPhase] = useState<IntentionPhase | null>(null);
  const [q, setQ] = useState("");
  const list = useIntentions(phase, q.trim());
  const counts = useIntentionCounts();
  const rows = list.data?.pages.flatMap((page) => page.data) ?? [];

  const counted = (key: IntentionPhase | null): number | null => {
    const data = counts.data;
    if (!data) return null;
    return key === null ? data.all : data[key];
  };

  let body: React.ReactNode;
  if (list.isError) {
    body = <ErrorState error={list.error} onRetry={() => void list.refetch()} />;
  } else if (list.isPending) {
    body = <div className="h-64 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  } else if (rows.length === 0) {
    body = (
      <p className="px-4 py-10 text-center text-[0.875rem] text-shell-muted" data-testid="intentions-empty">
        {phase === null && !q ? w.emptyAll : w.empty}
      </p>
    );
  } else {
    body = (
      <>
        <div
          className="hidden grid-cols-[minmax(0,1fr)_10rem_10rem_1rem] gap-x-4 border-b border-shell-line px-4 py-2.5 text-xs font-medium text-shell-muted md:grid"
          aria-hidden="true"
        >
          <span>{w.columns.intention}</span>
          <span>{w.columns.status}</span>
          <span>{w.columns.updated}</span>
          <span />
        </div>
        <ul aria-label={w.caption} className="divide-y divide-shell-line/70" data-testid="intentions">
          {rows.map((intention) => (
            <Row key={intention.id} intention={intention} />
          ))}
        </ul>
        {list.hasNextPage ? (
          <div className="border-t border-shell-line p-3 text-center">
            <button
              type="button"
              onClick={() => void list.fetchNextPage()}
              disabled={list.isFetchingNextPage}
              className="text-[0.8125rem] font-medium text-shell-nav-active hover:underline"
            >
              {w.more}
            </button>
          </div>
        ) : null}
      </>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title={w.title}
        subtitle={w.subtitle}
        actions={
          <Link href={routes.intentionNew()} className={buttonVariants()}>
            <Plus className="size-4" aria-hidden="true" />
            {w.new}
          </Link>
        }
      />
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
        <div role="group" aria-label={w.title} className="flex flex-wrap gap-2">
          {TABS.map((key) => {
            const count = counted(key);
            return (
              <button
                key={key ?? "all"}
                type="button"
                aria-pressed={phase === key}
                onClick={() => setPhase(key)}
                data-testid={`intentions-tab-${key ?? "all"}`}
                className={cn(
                  "flex items-center gap-2 rounded-lg border px-3 py-1.5 text-[0.8125rem] font-medium outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
                  phase === key
                    ? "border-brand-violet/30 bg-brand-violet-soft text-shell-nav-active"
                    : "border-shell-line bg-white text-brand-navy hover:bg-shell-canvas",
                )}
              >
                {w.phases[key ?? "all"]}
                {count !== null ? (
                  <span className="rounded-md bg-shell-canvas px-1.5 text-xs tabular-nums">
                    {count}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
        <label className="relative lg:ml-auto lg:w-80">
          <span className="sr-only">{w.search}</span>
          <Search
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-shell-muted"
            aria-hidden="true"
          />
          <Input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder={w.search}
            className="pl-9"
            data-testid="intentions-search"
          />
        </label>
      </div>
      <section className="overflow-hidden rounded-xl border border-shell-line bg-white">{body}</section>
    </PageContainer>
  );
}
