"use client";

import {
  ArrowRight,
  CircleAlert,
  CircleCheck,
  Lightbulb,
  type LucideIcon,
  Plus,
  ScanSearch,
  ShieldCheck,
  Sparkle,
  TriangleAlert,
  Waypoints,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { cn } from "cn";
import { FAMILY_ICON } from "@/components/approvals/parts";
import { items, wordItem } from "@/components/approvals/items";
import { CATEGORY_TONE, CHIP, KIND_ICON } from "@/components/activity/activity";
import { wordActivity } from "@/components/activity/items";
import { LekaInsights } from "@/components/insights/leka-insights";
import { CompactIntentionComposer } from "@/components/intentions/compact-composer";
import { PageContainer } from "@/components/shell/page-container";
import { useCurrentUser } from "@/components/shell/shell-provider";
import { exactDate, shortWhen } from "@/components/knowledge/time";
import { attentionRows } from "@/components/environment/parts";
import { ConnectedSources } from "@/components/sources/connected-sources";
import { routes } from "@/config/routes";
import { fill } from "@/lib/i18n/dictionaries";
import { useConflicts } from "@/lib/conflicts-queries";
import { useDecisionQueue } from "@/lib/decisions-queries";
import { useCandidates } from "@/lib/enrichment-queries";
import { useEnvironment } from "@/lib/environment-queries";
import { useActivity } from "@/lib/evolution-queries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import {
  isConnected,
  type Source,
  sourceTone,
  sources as sourcesApi,
} from "@/lib/sources";

/**
 * The overview, laid out as docs/product/mockups/01-vue-ensemble.jpeg.
 *
 * Every block of the mockup is here, in its place — and every figure on it
 * is real. What LEKA reads today is the workspace's sources (LEKA-344):
 * their states, their history, when each was last heard from. That fills
 * the greeting's status line, the "Sources connectées" tile, the sources
 * card, the activity and the banner.
 *
 * What LEKA does not collect yet — service health, incidents, insights,
 * approvals — the card says so in its own words, in the mockup's layout,
 * instead of showing the mockup's numbers (decided 2026-09-25). A "98 %"
 * shown to a customer who has connected nothing would be a lie about their
 * own company.
 */

type Load =
  | { status: "loading" }
  | { status: "failed" }
  | { status: "ready"; sources: Source[] };

const SOURCE_ROWS = 5;

function useOverviewData(): Load {
  const [load, setLoad] = useState<Load>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function run() {
      try {
        const { data: list } = await sourcesApi.list();
        if (!cancelled) setLoad({ status: "ready", sources: list });
      } catch {
        if (!cancelled) setLoad({ status: "failed" });
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, []);

  return load;
}

// ── Formatting ──────────────────────────────────────────────────────────────

function intlLocale(locale: string): string {
  return locale;
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// ── Building blocks ─────────────────────────────────────────────────────────

function Card({
  title,
  titleIcon,
  action,
  className,
  children,
}: {
  title: string;
  titleIcon?: React.ReactNode;
  action?: { label: string; href: string };
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className={cn("flex flex-col rounded-xl border border-shell-line bg-white p-3.5", className)}
    >
      <div className="mb-3 flex items-center gap-3">
        {titleIcon}
        <h2 className="flex-1 text-[1.0625rem] font-semibold tracking-[-0.01em] text-brand-navy">
          {title}
        </h2>
        {action ? (
          <Link
            href={action.href}
            className="flex items-center gap-1 rounded text-[0.8125rem] font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          >
            {action.label}
            <ArrowRight className="rtl:-scale-x-100 size-3.5" aria-hidden="true" />
          </Link>
        ) : null}
      </div>
      {children}
    </section>
  );
}

const TONE_TILE = {
  success: "bg-state-success-soft text-state-success",
  warning: "bg-state-warning-soft text-state-warning",
  danger: "bg-state-danger-soft text-state-danger",
  info: "bg-state-info-soft text-state-info",
  violet: "bg-brand-violet-soft text-shell-nav-active",
  neutral: "bg-shell-canvas text-shell-muted",
} as const;

type TileTone = keyof typeof TONE_TILE;

function IconTile({
  icon: Icon,
  tone,
  className,
  iconClassName,
}: {
  icon: LucideIcon;
  tone: TileTone;
  className?: string;
  iconClassName?: string;
}) {
  return (
    <span
      className={cn(
        "flex size-10 shrink-0 items-center justify-center rounded-lg",
        TONE_TILE[tone],
        className,
      )}
    >
      <Icon className={cn("size-5", iconClassName)} aria-hidden="true" />
    </span>
  );
}

function Empty({ icon, title, body }: { icon: LucideIcon; title: string; body?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-8 text-center">
      <IconTile icon={icon} tone="violet" />
      <p className="text-sm font-medium text-brand-navy">{title}</p>
      {body ? <p className="max-w-xs text-[0.8125rem] text-shell-muted">{body}</p> : null}
    </div>
  );
}

// ── The blocks of the mockup ───────────────────────────────────────────────

function Greeting({ load }: { load: Load }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const user = useCurrentUser();
  // The first name given at registration; an account made before it was
  // asked is greeted by the first part of its address until it gives one.
  const name = user?.first_name?.trim() || capitalise(user?.email.split("@")[0] ?? "");
  const today = capitalise(
    new Intl.DateTimeFormat(intlLocale(locale), {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
    }).format(new Date()),
  );

  let status = "";
  if (load.status === "failed") status = t.overview.loadFailed;
  if (load.status === "ready") {
    const needing = load.sources.filter((source) =>
      ["attention", "error"].includes(sourceTone(source)),
    ).length;
    if (load.sources.length === 0) status = t.overview.statusNoSources;
    else if (needing > 0) status = fill(t.overview.statusAttention, { count: needing });
    else status = t.overview.statusSynced;
  }

  return (
    <div>
      <p className="text-[0.8125rem] text-shell-muted">{today}</p>
      <h1 className="mt-1 text-[2.125rem] leading-tight font-bold tracking-[-0.02em] text-brand-navy">
        {fill(t.overview.greeting, { name })}
      </h1>
      {/* Held open while loading, so the page does not jump when it lands. */}
      <p
        className="min-h-8 text-[1.625rem] leading-8 tracking-[-0.01em] text-shell-accent-muted"
        aria-live="polite"
      >
        {status}
      </p>
      <p className="mt-1 text-[0.9375rem] text-shell-muted">{t.overview.tagline}</p>
    </div>
  );
}

function StateCard({ load, className }: { load: Load; className?: string }) {
  const t = useDictionary();
  const w = t.overview;
  const list = load.status === "ready" ? load.sources : [];
  const connected = list.filter(isConnected).length;
  // The environment as enrichment made it (LEKA-359, LEKA-369): services
  // and their state — a monitoring tool's word, or deduced from what runs
  // them — open incidents, what needs attention.
  const environment = useEnvironment();
  const env = environment.data;
  const attention = env ? attentionRows(t, env.attention) : [];
  // What needs someone: incidents, resources failed or stopped, work left
  // waiting. What is only worth knowing — nothing measures a service —
  // is said, not counted as an alarm.
  const pressing = attention.filter((row) => row.level !== "info");
  const points = env
    ? env.attention
        .filter((point) => point.level !== "info")
        .reduce((sum, point) => sum + point.count, 0)
    : null;
  const known = attention.find((row) => row.level === "info");
  const tiles = [
    {
      key: "services",
      icon: CircleCheck,
      tone: "success" as const,
      label: w.servicesUp,
      filled: true,
      // Nothing says how any of them is: not « 0 », which reads « all
      // down », nor « — », which reads « not loaded yet » — said in words,
      // not a « ? » (LEKA-438).
      value: !env
        ? null
        : env.services > 0 && env.services_unknown === env.services
          ? w.notMeasured
          : String(env.services_operational),
      foot: !env
        ? null
        : env.services === 0
          ? w.noServices
          : [
              fill(w.servicesOf, { total: env.services }),
              env.services_deduced ? w.deduced : null,
              env.services_unknown ? fill(w.unknown, { count: env.services_unknown }) : null,
              env.services_external
                ? fill(w.external, { count: env.services_external })
                : null,
            ]
              .filter(Boolean)
              .join(" · "),
    },
    {
      key: "attention",
      icon: CircleAlert,
      tone: "warning" as const,
      label: w.attentionPoints,
      value: points === null ? null : String(points),
      foot: !env
        ? null
        : pressing[0]
          ? pressing[0].detail || pressing[0].title
          : known
            ? fill(w.onlyKnown, { detail: known.detail || known.title })
            : w.noAttention,
    },
    {
      key: "incidents",
      icon: TriangleAlert,
      tone: "danger" as const,
      label: w.activeIncidents,
      value: env ? String(env.incidents_open) : null,
      foot: !env
        ? null
        : env.services_impacted
          ? fill(w.impacted, { count: env.services_impacted })
          : env.incidents_open
            ? null
            : w.noIncident,
    },
  ];

  return (
    <Card
      title={t.overview.stateTitle}
      action={{ label: t.overview.seeDetail, href: routes.environment() }}
      className={className}
    >
      {/* Each tile as tall as what it says (LEKA-438): stretched to the
          row, they were figures over a blank band. */}
      <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        {tiles.map(({ key, icon, tone, label, filled, value, foot }) => (
          <div
            key={key}
            className="flex flex-col rounded-lg border border-shell-line px-3 py-3.5"
            data-testid="kpi-tile"
            data-kpi={key}
          >
            <div className="flex items-start gap-3">
              <IconTile
                icon={icon}
                tone={tone}
                iconClassName={filled ? "fill-current [&>path]:stroke-white" : undefined}
              />
              <div className="min-w-0">
                <p
                  className={cn(
                    "font-bold text-brand-navy",
                    // A sentence ("Pas encore mesuré") on one line, not a figure's size.
                    value && !/^\d/.test(value) ? "text-sm leading-7" : "text-[1.375rem] leading-7",
                  )}
                  data-testid={`kpi-${key}`}
                >
                  {value ?? "—"}
                </p>
                <p className="text-[0.78rem] leading-4 tracking-[-0.01em] text-shell-muted">
                  {label}
                </p>
              </div>
            </div>
            <p className="line-clamp-2 pt-3 text-xs text-shell-muted">
              {environment.isError ? w.notRead : foot}
            </p>
          </div>
        ))}
        <div className="flex flex-col rounded-lg border border-shell-line px-3 py-3.5" data-testid="kpi-tile">
          <div className="flex items-start gap-3">
            <IconTile icon={Waypoints} tone="info" />
            <div className="min-w-0">
              <p
                className="text-[1.375rem] leading-7 font-bold text-brand-navy"
                data-testid="kpi-sources"
              >
                {load.status === "ready" ? connected : "—"}
              </p>
              <p className="text-[0.78rem] leading-4 tracking-[-0.01em] text-shell-muted">
                {t.overview.connectedSources}
              </p>
            </div>
          </div>
          <p className="pt-3 text-xs text-shell-muted">
            {load.status === "ready"
              ? fill(t.overview.sourcesRatio, { connected, total: list.length })
              : t.overview.notMeasured}
          </p>
        </div>
      </div>
    </Card>
  );
}

function InsightsCard() {
  const t = useDictionary();
  return (
    <section className="flex flex-col rounded-xl border border-shell-line bg-white p-3.5">
      <div className="mb-3 flex items-center gap-3">
        <IconTile icon={Lightbulb} tone="violet" className="size-9" />
        <h2 className="text-[1.0625rem] font-semibold tracking-[-0.01em] text-brand-navy">
          {t.overview.insightsTitle}
        </h2>
      </div>
      {/* What LEKA's analyses concluded (LEKA-377): two, so the card keeps
          the height of the state beside it. */}
      <LekaInsights shown={2} />
    </section>
  );
}


/** Mockup 01's "Activité récente": the last of what Activité tells — the
 * same events, worded the same way. It read the sources' sync history
 * only, and said "no activity" beside a page counting 36 (LEKA-438). */
function ActivityCard() {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const week = useActivity(7);
  const latest = (week.data?.latest ?? []).slice(0, 5);

  return (
    <Card
      title={t.overview.activityTitle}
      action={{ label: t.overview.seeAll, href: routes.activity() }}
    >
      {week.data && latest.length === 0 ? (
        <Empty icon={ScanSearch} title={t.overview.activityEmpty} />
      ) : (
        <ul className="divide-y divide-shell-line">
          {latest.map((item) => {
            const worded = wordActivity(t, item);
            const row = (
              <>
                <IconTile
                  icon={KIND_ICON[item.kind] ?? ScanSearch}
                  tone={CATEGORY_TONE[item.category]}
                  className="size-9"
                />
                <time
                  dateTime={item.at}
                  title={exactDate(locale, item.at)}
                  className="w-12 shrink-0 text-[0.8125rem] text-shell-muted tabular-nums"
                >
                  {shortWhen(locale, item.at)}
                </time>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-brand-navy">
                    {worded.title}
                  </span>
                  {worded.detail ? (
                    <span className="block truncate text-[0.8125rem] text-shell-accent-muted">
                      {worded.detail}
                    </span>
                  ) : null}
                </span>
                <span
                  className={cn(
                    "shrink-0 rounded-md px-2 py-0.5 text-xs font-medium",
                    CHIP[item.category],
                  )}
                >
                  {t.activity.category[item.category]}
                </span>
              </>
            );
            return (
              <li key={item.id} data-testid="activity-row">
                {worded.href ? (
                  <Link
                    href={worded.href}
                    className="-mx-1.5 flex items-center gap-4 rounded-lg px-1.5 py-2 outline-none hover:bg-shell-canvas focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                  >
                    {row}
                  </Link>
                ) : (
                  <div className="flex items-center gap-4 py-2">{row}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

/** What waits on someone: the actions intentions ask to do (LEKA-390), the
 * conflicts between sources to settle (LEKA-382), then the enrichments
 * LEKA proposes (LEKA-380) — three, each leading to itself in À valider. */
function ApprovalsCard() {
  const t = useDictionary();
  const proposed = useCandidates("proposed");
  const open = useConflicts("open");
  const waiting = useDecisionQueue("proposed");
  const all = items(proposed.data?.data ?? [], open.data?.data ?? [], waiting.data?.data ?? []);
  const shown = all.slice(0, 3);
  return (
    <Card
      title={t.overview.approvalsTitle}
      titleIcon={
        <Sparkle
          className="size-5 fill-shell-nav-active text-shell-nav-active"
          aria-hidden="true"
        />
      }
      action={{ label: t.overview.seeAll, href: routes.approvals() }}
    >
      {shown.length === 0 ? (
        <Empty
          icon={ShieldCheck}
          title={t.overview.approvalsEmpty}
          body={t.overview.approvalsEmptyBody}
        />
      ) : (
        <>
          <ul className="divide-y divide-shell-line/60" data-testid="approvals-waiting">
            {shown.map((item) => {
              const { title, why } = wordItem(t, item);
              const sure =
                item.kind === "candidate" ? ` · ${Math.round(item.data.confidence * 100)} %` : "";
              return (
                <li key={`${item.kind}:${item.id}`}>
                  <Link
                    href={
                      item.kind === "candidate"
                        ? routes.approval(item.id)
                        : `${routes.approval(item.id)}?kind=${item.kind}`
                    }
                    className="-mx-1.5 flex items-start gap-3 rounded-lg px-1.5 py-2.5 outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-brand-violet/40"
                  >
                    <IconTile
                      icon={FAMILY_ICON[item.family] ?? Sparkle}
                      tone="violet"
                      className="size-9"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[0.8125rem] leading-snug font-semibold text-brand-navy">
                        {title}
                      </span>
                      <span className="block truncate text-xs text-shell-muted">
                        {why ?? ""}
                        {sure}
                      </span>
                    </span>
                    <span className="mt-0.5 rounded-md bg-state-warning-soft px-2 py-0.5 text-xs font-medium whitespace-nowrap text-state-warning">
                      {item.kind === "conflict"
                        ? t.approvals.conflict.status.open
                        : item.kind === "decision"
                          ? t.decisions.statuses.proposed
                          : t.approvals.status.proposed}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
          {all.length > shown.length ? (
            <p className="mt-1 text-xs text-shell-muted">
              {fill(t.approvals.overview.waiting, { count: all.length })}
            </p>
          ) : null}
        </>
      )}
    </Card>
  );
}

function SourcesCard({ load }: { load: Load }) {
  const t = useDictionary();
  const list = load.status === "ready" ? load.sources : [];

  return (
    <Card
      title={t.overview.sourcesTitle}
      action={{ label: t.overview.seeAllSources, href: routes.sources() }}
    >
      {load.status === "ready" && list.length === 0 ? (
        <p className="py-4 text-center text-[0.8125rem] text-shell-muted">
          {t.overview.sourcesEmpty}
        </p>
      ) : (
        <ConnectedSources sources={list} max={SOURCE_ROWS} />
      )}
      <Link
        href={routes.sources()}
        className="mt-3 flex items-center justify-center gap-2 rounded-lg border border-shell-line px-4 py-2 text-sm font-medium text-brand-navy outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
      >
        <Plus className="size-4" aria-hidden="true" />
        {t.overview.addSource}
      </Link>
    </Card>
  );
}


// ── The page ───────────────────────────────────────────────────────────────

export function Overview() {
  const load = useOverviewData();

  return (
    <PageContainer>
      <Greeting load={load} />
      <div className="mt-5">
        <CompactIntentionComposer />
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,0.66fr)]">
        <StateCard load={load} className="xl:col-span-2 xl:self-start" />
        <InsightsCard />
        <ActivityCard />
        <ApprovalsCard />
        <SourcesCard load={load} />
      </div>
    </PageContainer>
  );
}
