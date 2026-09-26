"use client";

import {
  ArrowRight,
  ChartColumn,
  CircleAlert,
  CircleCheck,
  CircleOff,
  HeartPulse,
  KeyRound,
  Lightbulb,
  type LucideIcon,
  Plus,
  Power,
  ScanSearch,
  Settings2,
  ShieldCheck,
  Sparkle,
  Sparkles,
  Trash2,
  TriangleAlert,
  Waypoints,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { cn } from "cn";
import { CompactIntentionComposer } from "@/components/intentions/compact-composer";
import { PageContainer } from "@/components/shell/page-container";
import { useCurrentUser } from "@/components/shell/shell-provider";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { exactDate, shortWhen, timeAgo } from "@/components/knowledge/time";
import { SourceLogo } from "@/components/sources/source-logo";
import { routes } from "@/config/routes";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import {
  isConnected,
  lastSeen,
  type Source,
  type SourceEvent,
  type SourceTone,
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
  | { status: "ready"; sources: Source[]; events: TimedEvent[] };

interface TimedEvent extends SourceEvent {
  source: Source;
}

/** The activity card shows five; asking each source for five is enough. */
const EVENTS_PER_SOURCE = 5;
const ACTIVITY_ROWS = 5;
const SOURCE_ROWS = 5;

function useOverviewData(): Load {
  const [load, setLoad] = useState<Load>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function run() {
      try {
        const { data: list } = await sourcesApi.list();
        // One call per source, in parallel. A source whose history cannot
        // be read costs its lines in the activity, not the whole page.
        const histories = await Promise.all(
          list.map(async (source) => {
            try {
              const { data } = await sourcesApi.events(source.id, EVENTS_PER_SOURCE);
              return data.map((event) => ({ ...event, source }));
            } catch {
              return [];
            }
          }),
        );
        const events = histories
          .flat()
          .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
          .slice(0, ACTIVITY_ROWS);
        if (!cancelled) setLoad({ status: "ready", sources: list, events });
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
  return locale === "fr" ? "fr-FR" : "en-GB";
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
    <section className={cn("rounded-xl border border-shell-line bg-white p-3.5", className)}>
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
            <ArrowRight className="size-3.5" aria-hidden="true" />
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
  const { locale } = useLocale();
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
  const list = load.status === "ready" ? load.sources : [];
  const connected = list.filter(isConnected).length;

  // Three tiles LEKA cannot fill yet: no monitoring source reports service
  // health or incidents. Laid out as the mockup; valued "—", and saying why.
  const unmeasured = [
    {
      icon: CircleCheck,
      tone: "success" as const,
      label: t.overview.servicesUp,
      filled: true,
    },
    {
      icon: CircleAlert,
      tone: "warning" as const,
      label: t.overview.attentionPoints,
    },
    {
      icon: TriangleAlert,
      tone: "danger" as const,
      label: t.overview.activeIncidents,
    },
  ];

  return (
    <Card
      title={t.overview.stateTitle}
      action={{ label: t.overview.seeDetail, href: routes.environment() }}
      className={className}
    >
      <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        {unmeasured.map(({ icon, tone, label, filled }) => (
          <div
            key={label}
            className="rounded-lg border border-shell-line px-3 py-3.5"
            data-testid="kpi-tile"
          >
            <div className="flex items-start gap-3">
              <IconTile
                icon={icon}
                tone={tone}
                iconClassName={filled ? "fill-current [&>path]:stroke-white" : undefined}
              />
              <div className="min-w-0">
                <p className="text-[1.375rem] leading-7 font-bold text-brand-navy">—</p>
                <p className="text-[0.78rem] leading-4 tracking-[-0.01em] text-shell-muted">
                  {label}
                </p>
              </div>
            </div>
            <p className="mt-4 text-xs text-shell-muted">{t.overview.noMonitoring}</p>
          </div>
        ))}
        <div className="rounded-lg border border-shell-line px-3 py-3.5" data-testid="kpi-tile">
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
          <p className="mt-4 text-xs text-shell-muted">
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
      <p className="flex-1 text-[0.9375rem] leading-snug text-shell-muted">
        {t.overview.insightsEmpty}
      </p>
      <Link
        href={routes.intentionNew()}
        className="mt-4 flex items-center justify-center gap-2 rounded-lg bg-brand-navy px-4 py-2.5 text-sm font-medium text-white outline-none hover:bg-brand-navy/90 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
      >
        {t.overview.insightsAction}
        <ArrowRight className="size-4" aria-hidden="true" />
      </Link>
    </section>
  );
}

const EVENT_LOOK: Record<SourceEvent["type"], { icon: LucideIcon; tone: TileTone }> = {
  created: { icon: Plus, tone: "violet" },
  test_succeeded: { icon: CircleCheck, tone: "success" },
  test_failed: { icon: CircleAlert, tone: "danger" },
  activated: { icon: Power, tone: "success" },
  reconfigured: { icon: Settings2, tone: "info" },
  credentials_rotated: { icon: KeyRound, tone: "info" },
  health_changed: { icon: HeartPulse, tone: "warning" },
  disabled: { icon: CircleOff, tone: "warning" },
  deleted: { icon: Trash2, tone: "danger" },
  sync_failed: { icon: TriangleAlert, tone: "danger" },
  sync_recovered: { icon: CircleCheck, tone: "success" },
};

function ActivityCard({ load }: { load: Load }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const events = load.status === "ready" ? load.events : [];

  return (
    <Card
      title={t.overview.activityTitle}
      action={{ label: t.overview.seeAll, href: routes.activity() }}
    >
      {load.status === "ready" && events.length === 0 ? (
        <Empty icon={ScanSearch} title={t.overview.activityEmpty} />
      ) : (
        <ul className="divide-y divide-shell-line">
          {events.map((event) => {
            const look = EVENT_LOOK[event.type];
            return (
              <li
                key={event.id}
                className="flex items-center gap-4 py-2"
                data-testid="activity-row"
              >
                <IconTile icon={look.icon} tone={look.tone} className="size-9" />
                <time
                  dateTime={event.created_at}
                  title={exactDate(locale, event.created_at)}
                  className="w-12 shrink-0 text-[0.8125rem] text-shell-muted tabular-nums"
                >
                  {shortWhen(locale, event.created_at)}
                </time>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-brand-navy">
                    {t.overview.events[event.type]}
                  </span>
                  <span className="block truncate text-[0.8125rem] text-shell-accent-muted">
                    {event.source.display_name}
                  </span>
                </span>
                <span className="rounded-md bg-state-success-soft px-2 py-0.5 text-xs font-medium text-state-success">
                  {t.overview.eventKind}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

function ApprovalsCard() {
  const t = useDictionary();
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
      <Empty
        icon={ShieldCheck}
        title={t.overview.approvalsEmpty}
        body={t.overview.approvalsEmptyBody}
      />
    </Card>
  );
}

const SEVERITY: Record<SourceTone, number> = {
  error: 0,
  attention: 1,
  synced: 2,
  setup: 3,
  off: 4,
};

function SourcesCard({ load }: { load: Load }) {
  const t = useDictionary();
  const list = load.status === "ready" ? load.sources : [];
  // What needs a look first, then the rest, most recently heard from first.
  const shown = [...list]
    .sort(
      (a, b) =>
        SEVERITY[sourceTone(a)] - SEVERITY[sourceTone(b)] ||
        Date.parse(lastSeen(b) ?? "1970") - Date.parse(lastSeen(a) ?? "1970"),
    )
    .slice(0, SOURCE_ROWS);

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
        <ul className="space-y-1">
          {shown.map((source) => {
            const tone = sourceTone(source);
            const seen = lastSeen(source);
            return (
              <li
                key={source.id}
                className="flex items-center gap-3 py-1.5"
                data-testid="source-row"
              >
                <SourceLogo kind={source.type} className="size-5 shrink-0" />
                <span
                  title={source.display_name}
                  className="min-w-0 flex-1 truncate text-[0.8125rem] font-medium text-brand-navy"
                >
                  {source.display_name}
                </span>
                <StatusBadge variant={`source.${tone}`} />
                <span className="shrink-0 text-right text-xs whitespace-nowrap text-shell-muted">
                  {seen ? timeAgo(t, seen) : t.overview.neverSeen}
                </span>
              </li>
            );
          })}
        </ul>
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

function Banner({ load }: { load: Load }) {
  const t = useDictionary();
  const connected = load.status === "ready" ? load.sources.filter(isConnected).length : null;
  const stats: { icon: LucideIcon; value: string; label: string }[] = [
    {
      icon: ChartColumn,
      value: connected === null ? "—" : String(connected),
      label: t.overview.statSources,
    },
    // Correlation and contradiction are the analysis pipeline's (LEKA-384).
    { icon: ScanSearch, value: "—", label: t.overview.statEvents },
    { icon: Sparkles, value: "—", label: t.overview.statContradictions },
  ];

  return (
    <section className="mt-6 flex flex-col gap-4 rounded-xl bg-shell-highlight px-6 py-4 lg:flex-row lg:items-center">
      <div className="flex flex-1 items-start gap-4">
        <Sparkles className="mt-0.5 size-8 shrink-0 text-shell-nav-active" aria-hidden="true" />
        <div>
          <p className="text-[0.9375rem] font-semibold text-brand-navy">
            {connected
              ? fill(t.overview.bannerTitle, { count: connected })
              : t.overview.bannerTitleNone}
          </p>
          <p className="text-[0.8125rem] text-shell-muted">{t.overview.bannerBody}</p>
        </div>
      </div>
      {/* A plain list: value then label, read in that order. */}
      <ul className="flex divide-x divide-shell-line">
        {stats.map(({ icon: Icon, value, label }) => (
          <li key={label} className="flex items-center gap-3 px-5 first:pl-0 last:pr-0">
            <span className="flex size-10 items-center justify-center rounded-lg bg-white">
              <Icon className="size-5 text-shell-nav-active" aria-hidden="true" />
            </span>
            <p>
              <span className="block text-lg leading-6 font-bold text-brand-navy">{value}</span>
              <span className="block text-xs text-shell-muted">{label}</span>
            </p>
          </li>
        ))}
      </ul>
    </section>
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
        <StateCard load={load} className="xl:col-span-2" />
        <InsightsCard />
        <ActivityCard load={load} />
        <ApprovalsCard />
        <SourcesCard load={load} />
      </div>
      <Banner load={load} />
    </PageContainer>
  );
}
