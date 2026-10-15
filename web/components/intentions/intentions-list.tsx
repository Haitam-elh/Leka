"use client";

import { ArrowRight, ChevronRight, Layers, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { cn } from "cn";

import type { TileTone } from "@/components/environment/parts";
import { SummarySaid } from "@/components/intentions/analysis-tab";
import { JourneyPill } from "@/components/intentions/journey";
import { Pill } from "@/components/intelligence/pill";
import { timeAgo } from "@/components/knowledge/time";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { ErrorState } from "@/components/states/error-state";
import { StatePanel } from "@/components/states/state-panel";
import { buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { routes } from "@/config/routes";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { useCapabilities } from "@/lib/capabilities-queries";
import type { Intention, IntentionFilters, IntentionPhase, IntentionStatus } from "@/lib/intentions/api";
import { type Journey, journeyWhy } from "@/lib/intentions/journey";
import { useIntention, useIntentionCounts, useIntentions } from "@/lib/intentions/queries";
import { useSources } from "@/lib/sources-queries";

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
  needs_clarification: "warning",
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

/** Where it stands: its journey's state when it is given — the same on
 * every screen (LEKA-443) — else, from before, its lifecycle's. */
export function StatusPill({ status, journey }: { status: IntentionStatus; journey?: Journey }) {
  const t = useDictionary();
  if (journey) return <JourneyPill journey={journey} status={status} />;
  return (
    <Pill tone={STATUS_TONES[status]} dot data-testid="intention-status" data-status={status}>
      {t.intentions.statuses[status]}
    </Pill>
  );
}

export function kindOf(t: Dictionary, kind: string | null): string | null {
  return kind ? ((t.intent.kinds as Record<string, string>)[kind] ?? kind) : null;
}

/** Where the panel beside the list is drawn (xl): there, a row shows its
 * intention in it, as mockup 07; narrower, it opens its page. */
const WIDE = "(min-width: 1280px)";

function Row({
  intention,
  chosen,
  onChoose,
}: {
  intention: Intention;
  chosen: boolean;
  onChoose: (id: string) => void;
}) {
  const t = useDictionary();
  const kind = kindOf(t, intention.kind);
  return (
    <li data-testid="intention-row" data-chosen={chosen || undefined}>
      <Link
        href={routes.intention(intention.id)}
        aria-current={chosen || undefined}
        onClick={(event) => {
          // A modified click is the person's: a new tab, a new window.
          if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
          if (window.matchMedia?.(WIDE).matches) {
            event.preventDefault();
            onChoose(intention.id);
          }
        }}
        className={cn(
          "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-1 px-4 py-3 outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-brand-violet/40 md:grid-cols-[minmax(0,1fr)_10rem_10rem_1rem]",
          chosen && "bg-brand-violet-soft/50 shadow-[inset_3px_0_0_var(--brand-violet)]",
        )}
      >
        <span className="min-w-0">
          <span className="block truncate text-[0.9375rem] font-semibold text-brand-navy">
            {intention.title}
          </span>
          {kind ? <span className="block text-[0.8125rem] text-shell-muted">{kind}</span> : null}
        </span>
        <span>
          <StatusPill status={intention.status} journey={intention.journey} />
        </span>
        <span className="col-span-2 text-[0.8125rem] text-shell-muted md:col-span-1">
          {timeAgo(t, intention.updated_at)}
        </span>
        <ChevronRight className="rtl:-scale-x-100 hidden size-4 text-shell-muted md:block" aria-hidden="true" />
      </Link>
    </li>
  );
}

/** Mockup 07's panel: the latest intention — where it stands, what it came
 * to — and the way to its analysis. */
function Preview({ id, chosen }: { id: string; chosen: boolean }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.intentions.preview;
  const { data } = useIntention(id);
  if (!data) return <div className="h-64 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  const ago = timeAgo(t, data.created_at);
  const why = journeyWhy(t, data.journey);
  return (
    <aside
      aria-label={w.title}
      className="flex flex-col gap-3 rounded-xl border border-shell-line bg-white p-4"
      data-testid="intention-preview"
    >
      <div>
        <p className="text-xs font-medium tracking-wide text-shell-nav uppercase">
          {chosen ? w.chosen : w.latest}
        </p>
        <h2 className="mt-1 text-[1.0625rem] font-semibold text-brand-navy" dir="auto">
          {data.title}
        </h2>
        <p className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-shell-muted">
          <StatusPill status={data.status} journey={data.journey} />
          {fill(t.intentions.created, {
            when: ago.charAt(0).toLocaleLowerCase(locale) + ago.slice(1),
          })}
        </p>
        {/* What happened, as its page says it: an error, a partial result,
            stays in sight here too (LEKA-443). */}
        {why ? (
          <p className="mt-1.5 text-[0.8125rem] text-brand-navy" data-testid="preview-why">
            {why}
          </p>
        ) : null}
      </div>
      <div>
        <h3 className="mb-1 text-[0.875rem] font-semibold text-brand-navy">{w.summary}</h3>
        <SummarySaid intention={data} none={t.intentions.overview.noSummary} />
      </div>
      <Link href={routes.intention(id)} className={buttonVariants({ className: "w-full" })}>
        {w.open}
        <ArrowRight className="rtl:-scale-x-100 size-4" aria-hidden="true" />
      </Link>
    </aside>
  );
}

const SELECT =
  "h-9 rounded-md border border-shell-line bg-white px-2 text-[0.8125rem] text-brand-navy outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40";
const PERIODS = [7, 30, 90] as const;

/** By agent, source, period, and the order (LEKA-457): what the API filters, nothing here. */
function Filters({
  value,
  onChange,
}: {
  value: IntentionFilters;
  onChange: (next: IntentionFilters) => void;
}) {
  const w = useDictionary().intentions.filters;
  const agents = (useCapabilities({}).data ?? []).filter((c) => c.kind === "agent");
  const sources = useSources().data ?? [];
  const set = (patch: IntentionFilters) => onChange({ ...value, ...patch });
  return (
    <div className="mb-4 flex flex-wrap gap-2" data-testid="intentions-filters">
      <select
        aria-label={w.agent}
        value={value.agent ?? ""}
        onChange={(e) => set({ agent: e.target.value || undefined })}
        className={SELECT}
        data-testid="intentions-filter-agent"
      >
        <option value="">{w.anyAgent}</option>
        {agents.map((agent) => (
          <option key={agent.key} value={agent.key}>
            {agent.title}
          </option>
        ))}
      </select>
      <select
        aria-label={w.source}
        value={value.source ?? ""}
        onChange={(e) => set({ source: e.target.value || undefined })}
        className={SELECT}
        data-testid="intentions-filter-source"
      >
        <option value="">{w.anySource}</option>
        {sources.map((source) => (
          <option key={source.id} value={source.id}>
            {source.display_name}
          </option>
        ))}
      </select>
      <select
        aria-label={w.period}
        value={value.days ?? ""}
        onChange={(e) => set({ days: Number(e.target.value) || undefined })}
        className={SELECT}
        data-testid="intentions-filter-period"
      >
        <option value="">{w.periods.all}</option>
        {PERIODS.map((days) => (
          <option key={days} value={days}>
            {w.periods[days]}
          </option>
        ))}
      </select>
      <select
        aria-label={w.sort}
        value={value.sort ?? "updated"}
        onChange={(e) => set({ sort: e.target.value as IntentionFilters["sort"] })}
        className={SELECT}
        data-testid="intentions-sort"
      >
        {(["updated", "newest", "oldest"] as const).map((sort) => (
          <option key={sort} value={sort}>
            {w.sorts[sort]}
          </option>
        ))}
      </select>
    </div>
  );
}

export function IntentionsList() {
  const t = useDictionary();
  const w = t.intentions;
  const [phase, setPhase] = useState<IntentionPhase | null>(null);
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState<IntentionFilters>({});
  const list = useIntentions(phase, q.trim(), filters);
  const filtered = Boolean(filters.agent || filters.source || filters.days);
  const counts = useIntentionCounts();
  const rows = list.data?.pages.flatMap((page) => page.data) ?? [];
  // The one shown beside the list: the one chosen, else the latest.
  const [chosen, setChosen] = useState<string | null>(null);
  const previewed = rows.find((row) => row.id === chosen) ?? rows[0];

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
  } else if (rows.length === 0 && phase === null && !q && !filtered) {
    // Nothing asked yet: what asking does, and the way to it (LEKA-438).
    body = (
      <StatePanel
        icon={Layers}
        title={w.emptyAll}
        description={w.emptyAllBody}
        size="section"
        testId="intentions-empty"
        actions={
          <Link href={routes.intentionNew()} className={buttonVariants()}>
            <Plus className="size-4" aria-hidden="true" />
            {w.new}
          </Link>
        }
      />
    );
  } else if (rows.length === 0) {
    body = (
      <p className="px-4 py-10 text-center text-[0.875rem] text-shell-muted" data-testid="intentions-empty">
        {w.empty}
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
            <Row
              key={intention.id}
              intention={intention}
              chosen={intention.id === previewed?.id}
              onChoose={setChosen}
            />
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
        <label className="relative lg:ms-auto lg:w-80">
          <span className="sr-only">{w.search}</span>
          <Search
            className="pointer-events-none absolute top-1/2 start-3 size-4 -translate-y-1/2 text-shell-muted"
            aria-hidden="true"
          />
          <Input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder={w.search}
            className="ps-9"
            data-testid="intentions-search"
          />
        </label>
      </div>
      <Filters value={filters} onChange={setFilters} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,22rem)] xl:items-start">
        <section className="overflow-hidden rounded-xl border border-shell-line bg-white">{body}</section>
        {previewed ? (
          <div className="hidden xl:block">
            <Preview id={previewed.id} chosen={previewed.id === chosen} />
          </div>
        ) : null}
      </div>
    </PageContainer>
  );
}
