"use client";

import {
  ChevronLeft,
  ChevronRight,
  Code2,
  FileText,
  GitBranch,
  Layers,
  Network,
  Plus,
  Search,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { cn } from "cn";

import type { TileTone } from "@/components/environment/parts";
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
import type {
  Intention,
  IntentionFilters,
  IntentionStatus,
} from "@/lib/intentions/api";
import { type Journey, journeyWhy } from "@/lib/intentions/journey";
import { useIntentionCounts, useIntentions } from "@/lib/intentions/queries";
import { useSources } from "@/lib/sources-queries";
import { SourceLogo } from "@/components/sources/source-logo";
import { KIND_CATEGORY as SOURCE_KINDS, type SourceKind } from "@/lib/sources";

/**
 * L'historique des intentions (LEKA-457, the sprint's mockup): a table —
 * what was asked, the agents that ran, the sources it read, where it
 * stands, what it came to, when — by tab of states, searched, filtered,
 * eight a page. Every row and count is the API's (GET /intentions, its
 * counts by state).
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

/** Where it stands: its journey's state when it is given — the same on
 * every screen (LEKA-443) — else, from before, its lifecycle's. */
export function StatusPill({
  status,
  journey,
}: {
  status: IntentionStatus;
  journey?: Journey;
}) {
  const t = useDictionary();
  if (journey) return <JourneyPill journey={journey} status={status} />;
  return (
    <Pill
      tone={STATUS_TONES[status]}
      dot
      data-testid="intention-status"
      data-status={status}
    >
      {t.intentions.statuses[status]}
    </Pill>
  );
}

export function kindOf(t: Dictionary, kind: string | null): string | null {
  return kind
    ? ((t.intent.kinds as Record<string, string>)[kind] ?? kind)
    : null;
}

/** The mockup's tabs: a state's colour, the states it holds. */
const TABS: readonly {
  key: "all" | "running" | "done" | "waiting" | "failed" | "archived";
  dot?: string;
  statuses?: readonly IntentionStatus[];
}[] = [
  { key: "all" },
  {
    key: "running",
    dot: "bg-blue-500",
    statuses: ["submitted", "analysing", "approved", "executing", "verifying"],
  },
  {
    key: "done",
    dot: "bg-emerald-500",
    statuses: ["completed", "rejected", "cancelled"],
  },
  {
    key: "waiting",
    dot: "bg-amber-500",
    statuses: ["needs_clarification", "awaiting_decision", "scheduled"],
  },
  { key: "failed", dot: "bg-rose-500", statuses: ["failed"] },
  { key: "archived", dot: "bg-slate-400" },
];
type Tab = (typeof TABS)[number]["key"];

const PAGE = 8;

/** What it asks, as a tile: its kind's mark. */
const KIND_MARK: Record<string, { icon: LucideIcon; tone: string }> = {
  diagnose: { icon: TriangleAlert, tone: "bg-rose-50 text-rose-500" },
  change: { icon: Code2, tone: "bg-violet-50 text-violet-600" },
  ownership: { icon: UserRound, tone: "bg-sky-50 text-sky-600" },
  dependency: { icon: Network, tone: "bg-blue-50 text-blue-600" },
  compliance: { icon: ShieldCheck, tone: "bg-emerald-50 text-emerald-600" },
  migration: { icon: GitBranch, tone: "bg-amber-50 text-amber-600" },
  knowledge: { icon: FileText, tone: "bg-blue-50 text-blue-600" },
};
const GENERAL = {
  icon: Sparkles,
  tone: "bg-brand-violet-soft text-brand-violet",
};

const COLUMNS =
  "md:grid-cols-[minmax(0,2.2fr)_minmax(0,1fr)_7rem_8rem_minmax(0,1.4fr)_8.5rem_1rem]";

function Row({
  intention,
  agentTitle,
}: {
  intention: Intention;
  agentTitle: (key: string) => string;
}) {
  const t = useDictionary();
  const { format } = useLocale();
  const w = t.intentions.historyPage;
  const { icon: Icon, tone } = KIND_MARK[intention.kind ?? ""] ?? GENERAL;
  const result = intention.summary || journeyWhy(t, intention.journey);
  const [first, ...more] = intention.agents ?? [];
  return (
    <li data-testid="intention-row">
      <Link
        href={routes.intention(intention.id)}
        className={cn(
          "grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 rounded-xl border border-shell-line bg-white px-4 py-3 outline-none hover:border-brand-violet/40 focus-visible:ring-3 focus-visible:ring-brand-violet/40",
          COLUMNS,
        )}
      >
        <span className="flex min-w-0 items-center gap-3">
          <span
            className={cn(
              "flex size-11 shrink-0 items-center justify-center rounded-xl",
              tone,
            )}
          >
            <Icon className="size-5" aria-hidden="true" />
          </span>
          <span className="min-w-0">
            <span
              className="block truncate font-semibold text-brand-navy"
              dir="auto"
            >
              {intention.title}
            </span>
            <span
              className="line-clamp-2 text-[0.8125rem] text-shell-muted"
              dir="auto"
            >
              {intention.text}
            </span>
          </span>
        </span>
        <span
          className="hidden min-w-0 md:block"
          data-testid="intention-agents"
        >
          {first ? (
            <span className="inline-flex max-w-full items-center gap-1.5 rounded-lg bg-shell-canvas px-2.5 py-1 text-[0.8125rem] text-brand-navy">
              <span className="truncate">{agentTitle(first)}</span>
              {more.length ? (
                <span className="text-shell-muted">+{more.length}</span>
              ) : null}
            </span>
          ) : (
            <span className="text-shell-muted">{w.none}</span>
          )}
        </span>
        <span
          className="hidden items-center gap-2 md:flex"
          data-testid="intention-sources"
        >
          {(intention.sources ?? []).length ? (
            (intention.sources ?? [])
              .slice(0, 3)
              .map((kind) =>
                kind in SOURCE_KINDS ? (
                  <SourceLogo
                    key={kind}
                    kind={kind as SourceKind}
                    className="size-6"
                  />
                ) : null,
              )
          ) : (
            <span className="text-shell-muted">{w.none}</span>
          )}
        </span>
        <span>
          <StatusPill status={intention.status} journey={intention.journey} />
        </span>
        <span className="col-span-2 line-clamp-2 text-[0.8125rem] text-brand-navy md:col-span-1">
          {result || <span className="text-shell-muted">{w.none}</span>}
        </span>
        <span className="col-span-2 text-[0.8125rem] md:col-span-1">
          <span className="block text-brand-navy">
            {timeAgo(t, intention.updated_at)}
          </span>
          <span className="block text-xs text-shell-muted">
            {new Intl.DateTimeFormat(format, {
              dateStyle: "medium",
              timeStyle: "short",
            }).format(new Date(intention.updated_at))}
          </span>
        </span>
        <ChevronRight
          className="rtl:-scale-x-100 hidden size-4 text-shell-muted md:block"
          aria-hidden="true"
        />
      </Link>
    </li>
  );
}

const SELECT =
  "h-11 rounded-md border border-shell-line bg-white px-2 text-[0.8125rem] text-brand-navy outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40";
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
  const agents = (useCapabilities({}).data ?? []).filter(
    (c) => c.kind === "agent",
  );
  const sources = useSources().data ?? [];
  const set = (patch: IntentionFilters) => onChange({ ...value, ...patch });
  return (
    <div className="flex flex-wrap gap-2" data-testid="intentions-filters">
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
        onChange={(e) =>
          set({ sort: e.target.value as IntentionFilters["sort"] })
        }
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
  const h = w.historyPage;
  const [tab, setTab] = useState<Tab>("all");
  const [q, setQ] = useState("");
  const [filters, setFilters] = useState<IntentionFilters>({});
  const [page, setPage] = useState(0);
  const chosen = TABS.find((x) => x.key === tab);
  const asked = useMemo(
    () => ({ ...filters, statuses: chosen?.statuses }),
    [filters, chosen],
  );
  const list = useIntentions(
    tab === "archived" ? "archived" : null,
    q.trim(),
    asked,
    PAGE,
  );
  const counts = useIntentionCounts();
  const agents = useCapabilities({}).data;
  const agentTitle = (key: string) =>
    agents?.find((a) => a.key === key)?.title ?? key;
  const pages = list.data?.pages ?? [];
  const rows = pages[page]?.data ?? [];
  const filtered = Boolean(filters.agent || filters.source || filters.days);

  const counted = (key: Tab): number | null => {
    const data = counts.data;
    if (!data) return null;
    if (key === "all") return data.all;
    if (key === "archived") return data.archived;
    const holds = TABS.find((x) => x.key === key)?.statuses ?? [];
    return holds.reduce(
      (sum, status) => sum + (data.statuses?.[status] ?? 0),
      0,
    );
  };
  const total = counted(tab);
  const last = total === null ? page + 1 : Math.max(1, Math.ceil(total / PAGE));

  // A page not read yet: the ones before it, read in turn — a cursor leads
  // only to the next.
  async function goTo(index: number) {
    let read = pages.length;
    while (read <= index && list.hasNextPage) {
      const next = await list.fetchNextPage();
      read = next.data?.pages.length ?? read + 1;
    }
    setPage(index);
  }
  function reset<T>(set: (value: T) => void) {
    return (value: T) => {
      set(value);
      setPage(0);
    };
  }

  let body: React.ReactNode;
  if (list.isError) {
    body = (
      <ErrorState error={list.error} onRetry={() => void list.refetch()} />
    );
  } else if (list.isPending) {
    body = (
      <div
        className="h-64 animate-pulse rounded-xl bg-shell-canvas"
        aria-hidden="true"
      />
    );
  } else if (rows.length === 0 && tab === "all" && !q && !filtered) {
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
      <p
        className="px-4 py-10 text-center text-[0.875rem] text-shell-muted"
        data-testid="intentions-empty"
      >
        {w.empty}
      </p>
    );
  } else {
    body = (
      <>
        <div
          className={cn(
            "hidden gap-x-4 px-4 pb-2 text-xs font-medium tracking-wide text-shell-muted uppercase md:grid",
            COLUMNS,
          )}
          aria-hidden="true"
        >
          <span>{h.columns.intention}</span>
          <span>{h.columns.agents}</span>
          <span>{h.columns.sources}</span>
          <span>{h.columns.status}</span>
          <span>{h.columns.result}</span>
          <span>{h.columns.date}</span>
          <span />
        </div>
        <ul
          aria-label={w.caption}
          className="flex flex-col gap-2"
          data-testid="intentions"
        >
          {rows.map((intention) => (
            <Row
              key={intention.id}
              intention={intention}
              agentTitle={agentTitle}
            />
          ))}
        </ul>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-[0.875rem] text-shell-muted">
          <span data-testid="intentions-range">
            {fill(h.range, {
              from: page * PAGE + 1,
              to: page * PAGE + rows.length,
              total: total ?? page * PAGE + rows.length,
            })}
          </span>
          <nav
            aria-label={h.page.replace(" {n}", "")}
            className="flex items-center gap-1.5"
          >
            <button
              type="button"
              onClick={() => void goTo(page - 1)}
              disabled={page === 0}
              aria-label={h.previous}
              className={PAGER}
            >
              <ChevronLeft
                className="rtl:-scale-x-100 size-4"
                aria-hidden="true"
              />
            </button>
            {Array.from({ length: last }, (_, index) => index)
              .slice(Math.max(0, page - 2), Math.max(0, page - 2) + 5)
              .map((index) => (
                <button
                  key={index}
                  type="button"
                  onClick={() => void goTo(index)}
                  aria-label={fill(h.page, { n: index + 1 })}
                  aria-current={index === page ? "page" : undefined}
                  className={cn(
                    PAGER,
                    index === page &&
                      "border-brand-violet bg-brand-violet text-white",
                  )}
                >
                  {index + 1}
                </button>
              ))}
            <button
              type="button"
              onClick={() => void goTo(page + 1)}
              disabled={
                page + 1 >= last &&
                !(page + 1 < pages.length || list.hasNextPage)
              }
              aria-label={h.next}
              className={PAGER}
              data-testid="intentions-next"
            >
              <ChevronRight
                className="rtl:-scale-x-100 size-4"
                aria-hidden="true"
              />
            </button>
          </nav>
        </div>
      </>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title={h.title}
        subtitle={h.subtitle}
        actions={
          <Link
            href={routes.intentionNew()}
            className={cn(buttonVariants(), "h-11 bg-brand-violet px-5 hover:bg-brand-violet/90")}
          >
            <Plus className="size-4" aria-hidden="true" />
            {w.new}
          </Link>
        }
      />
      <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center">
        <label className="relative lg:flex-1">
          <span className="sr-only">{w.search}</span>
          <Search
            className="pointer-events-none absolute top-1/2 start-3 size-4 -translate-y-1/2 text-shell-muted"
            aria-hidden="true"
          />
          <Input
            value={q}
            onChange={(event) => reset(setQ)(event.target.value)}
            placeholder={w.search}
            className="h-11 ps-9"
            data-testid="intentions-search"
          />
        </label>
        <Filters value={filters} onChange={reset(setFilters)} />
      </div>
      <div
        className="mb-4 flex flex-wrap gap-2"
        role="group"
        aria-label={h.title}
      >
        {TABS.map(({ key, dot }) => {
          const count = counted(key);
          return (
            <button
              key={key}
              type="button"
              aria-pressed={tab === key}
              onClick={() => reset(setTab)(key)}
              data-testid={`intentions-tab-${key}`}
              className={cn(
                "flex items-center gap-2.5 rounded-xl border px-4 py-2.5 text-[0.875rem] font-medium outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
                tab === key
                  ? "border-brand-violet/40 bg-brand-violet-soft text-shell-nav-active"
                  : "border-shell-line bg-white text-brand-navy hover:bg-shell-canvas",
              )}
            >
              {dot ? (
                <span
                  className={cn("size-2 rounded-full", dot)}
                  aria-hidden="true"
                />
              ) : null}
              {h.tabs[key]}
              {count !== null ? (
                <span className="tabular-nums">{count}</span>
              ) : null}
            </button>
          );
        })}
      </div>
      <section>{body}</section>
    </PageContainer>
  );
}

const PAGER =
  "flex size-9 items-center justify-center rounded-lg border border-shell-line bg-white text-sm text-brand-navy outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-brand-violet/40 disabled:opacity-40";
