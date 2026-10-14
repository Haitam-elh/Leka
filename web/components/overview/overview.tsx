"use client";

import {
  ArrowRight,
  CircleCheck,
  Lightbulb,
  type LucideIcon,
  ScanSearch,
  ShieldCheck,
  Sparkle,
  TriangleAlert,
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
import { FirstStepsCard } from "@/components/overview/first-steps";
import { PageContainer } from "@/components/shell/page-container";
import { useCurrentUser } from "@/components/shell/shell-provider";
import { exactDate, shortWhen } from "@/components/knowledge/time";
import { entityHref } from "@/components/environment/parts";
import {
  askAbout,
  FreshnessLine,
  intentionHref,
  TwinBadge,
  twinHow,
} from "@/components/environment/twin";
import { StatusPill } from "@/components/intentions/intentions-list";
import { routes } from "@/config/routes";
import { fill } from "@/lib/i18n/dictionaries";
import { useConflicts } from "@/lib/conflicts-queries";
import { useDecisionQueue } from "@/lib/decisions-queries";
import { useCandidates } from "@/lib/enrichment-queries";
import { useEnvironment, useMonitoring } from "@/lib/environment-queries";
import { useIntentions } from "@/lib/intentions/queries";
import { byState, TROUBLE } from "@/lib/twin";
import { useActivity } from "@/lib/evolution-queries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { type Source, sourceTone, sources as sourcesApi } from "@/lib/sources";

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
      className={cn(
        "flex flex-col rounded-xl border border-shell-line bg-white p-3.5",
        className,
      )}
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
            <ArrowRight
              className="rtl:-scale-x-100 size-3.5"
              aria-hidden="true"
            />
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

function Empty({
  icon,
  title,
  body,
}: {
  icon: LucideIcon;
  title: string;
  body?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-8 text-center">
      <IconTile icon={icon} tone="violet" />
      <p className="text-sm font-medium text-brand-navy">{title}</p>
      {body ? (
        <p className="max-w-xs text-[0.8125rem] text-shell-muted">{body}</p>
      ) : null}
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
  const name =
    user?.first_name?.trim() || capitalise(user?.email.split("@")[0] ?? "");
  const today = capitalise(
    new Intl.DateTimeFormat(intlLocale(locale), {
      weekday: "long",
      day: "numeric",
      month: "long",
      year: "numeric",
    }).format(new Date()),
  );

  const environment = useEnvironment();
  const env = environment.data;
  let status = "";
  if (load.status === "failed") status = t.overview.loadFailed;
  if (load.status === "ready") {
    const needing = load.sources.filter((source) =>
      ["attention", "error"].includes(sourceTone(source)),
    ).length;
    const trouble =
      (env?.states?.unavailable ?? 0) + (env?.states?.degraded ?? 0);
    if (load.sources.length === 0) status = t.overview.statusNoSources;
    // What is in trouble first, then late reads, then sources: the twin's word.
    else if (trouble > 0)
      status = fill(t.overview.twin.statusTrouble, { count: trouble });
    else if (env?.freshness?.late) status = t.overview.twin.statusLate;
    else if (needing > 0)
      status = fill(t.overview.statusAttention, { count: needing });
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
      <p className="mt-1 text-[0.9375rem] text-shell-muted">
        {t.overview.tagline}
      </p>
    </div>
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
  const all = items(
    proposed.data?.data ?? [],
    open.data?.data ?? [],
    waiting.data?.data ?? [],
  );
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
          <ul
            className="divide-y divide-shell-line/60"
            data-testid="approvals-waiting"
          >
            {shown.map((item) => {
              const { title, why } = wordItem(t, item);
              const sure =
                item.kind === "candidate"
                  ? ` · ${Math.round(item.data.confidence * 100)} %`
                  : "";
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

/** « Qu'est-ce qui ne va pas, maintenant ? » — what the twin says is
 * unavailable or degraded, the worst first, each its state, how it is
 * known and the way to analyse it; what nothing says is said apart, never
 * « sain » (LEKA-442). The alerts the plan includes — or the plan that
 * would. */
function TroubleCard() {
  const t = useDictionary();
  const w = t.overview.twin;
  const environment = useEnvironment();
  const monitoring = useMonitoring();
  const env = environment.data;
  const trouble = byState(
    (env?.nodes ?? []).filter((n) => n.twin && TROUBLE.has(n.twin.state)),
  );
  const silent = (env?.states?.unknown ?? 0) + (env?.states?.not_covered ?? 0);
  const entitlement = monitoring.data?.entitlement;
  return (
    <Card
      title={w.troubleTitle}
      action={{ label: t.overview.seeAll, href: routes.environment() }}
    >
      {!env ? (
        <div
          className="h-24 animate-pulse rounded-lg bg-shell-canvas"
          aria-hidden="true"
        />
      ) : (
        <div className="flex flex-col gap-2" data-testid="overview-trouble">
          {trouble.length === 0 ? (
            <Empty icon={CircleCheck} title={w.troubleNone} />
          ) : (
            <ul className="divide-y divide-shell-line">
              {trouble.slice(0, 4).map((node) => (
                <li
                  key={node.id}
                  className="flex items-center gap-3 py-2"
                  data-state={node.twin?.state}
                >
                  {node.twin ? (
                    <TwinBadge state={node.twin.state} size="sm" />
                  ) : null}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-brand-navy">
                      {node.entity_id ? (
                        <Link
                          href={entityHref({
                            id: node.entity_id,
                            type: node.type,
                          })}
                          className="hover:underline"
                        >
                          {node.name}
                        </Link>
                      ) : (
                        node.name
                      )}
                    </span>
                    {node.twin ? (
                      <span className="block truncate text-xs text-shell-muted">
                        {twinHow(t, node.twin)}
                      </span>
                    ) : null}
                  </span>
                  {node.twin ? (
                    <Link
                      href={intentionHref(
                        askAbout(t, node.name, node.twin.state),
                      )}
                      className="shrink-0 text-xs font-medium text-shell-nav-active hover:underline"
                    >
                      {w.analyse}
                    </Link>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
          {silent > 0 ? (
            <p
              className="text-xs text-shell-muted"
              data-testid="overview-silent"
            >
              {fill(w.silent, { count: silent })}
            </p>
          ) : null}
          {entitlement ? (
            entitlement.proactive ? (
              <p
                className="text-xs text-shell-muted"
                data-testid="overview-alerts"
              >
                {fill(w.alertsOpen, {
                  count: monitoring.data?.open.length ?? 0,
                })}
              </p>
            ) : (
              <p
                className="text-xs text-shell-muted"
                data-testid="overview-alerts-limit"
              >
                {fill(w.alertsFrom, {
                  plan: (entitlement.alerts_from ?? "").replace(/^./, (c) =>
                    c.toUpperCase(),
                  ),
                })}{" "}
                <Link
                  href={routes.billing()}
                  className="text-shell-nav-active underline underline-offset-2"
                >
                  {w.seePlans}
                </Link>
              </p>
            )
          ) : null}
        </div>
      )}
    </Card>
  );
}

/** « Où en sont mes demandes ? » — the intentions under way, each its
 * status, the way to it. */
function IntentionsCard() {
  const t = useDictionary();
  const w = t.overview.twin;
  const list = useIntentions("active", "");
  const rows = (list.data?.pages ?? [])
    .flatMap((page) => page.data)
    .slice(0, 4);
  return (
    <Card
      title={w.intentionsTitle}
      action={{ label: t.overview.seeAll, href: routes.intentions() }}
    >
      {list.data && rows.length === 0 ? (
        <Empty icon={Sparkle} title={w.intentionsNone} />
      ) : (
        <ul
          className="divide-y divide-shell-line"
          data-testid="overview-intentions"
        >
          {rows.map((intention) => (
            <li key={intention.id}>
              <Link
                href={routes.intention(intention.id)}
                className="-mx-1.5 flex items-center gap-3 rounded-lg px-1.5 py-2 outline-none hover:bg-shell-canvas focus-visible:ring-2 focus-visible:ring-brand-violet/40"
              >
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-brand-navy">
                  {intention.title}
                </span>
                <StatusPill status={intention.status} journey={intention.journey} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** « Puis-je me fier à ce que LEKA voit ? » — when the sources were read,
 * those failing, late or never read, and what no source covers; nothing
 * when all is read and covered, said so. */
function FreshnessCard() {
  const t = useDictionary();
  const w = t.overview.twin;
  const environment = useEnvironment();
  const env = environment.data;
  const unwell = (env?.sources ?? []).filter(
    (s) => s.state !== "read" && s.state !== "syncing",
  );
  const uncovered = (env?.coverage ?? []).filter((c) => !c.covered);
  const parts = t.environment.twin.coverage.parts;
  return (
    <Card
      title={w.freshnessTitle}
      action={{ label: t.overview.seeAllSources, href: routes.sources() }}
    >
      {!env ? (
        <div
          className="h-24 animate-pulse rounded-lg bg-shell-canvas"
          aria-hidden="true"
        />
      ) : (
        <div
          className="flex flex-col gap-2 text-[0.8125rem]"
          data-testid="overview-freshness"
        >
          {(env.sources ?? []).length === 0 ? (
            // Nothing connected: nothing read, nothing covered — said once.
            <p className="text-shell-muted">{t.overview.sourcesEmpty}</p>
          ) : (
            <FreshnessLine freshness={env.freshness} />
          )}
          {(env.sources ?? []).length > 0 &&
          unwell.length === 0 &&
          uncovered.length === 0 ? (
            <p className="text-shell-muted">{w.allRead}</p>
          ) : null}
          {unwell.length ? (
            <ul className="space-y-1">
              {unwell.slice(0, 4).map((source) => (
                <li
                  key={source.id}
                  className="flex items-center gap-2"
                  data-state={source.state}
                >
                  <TriangleAlert
                    className="size-4 shrink-0 text-state-warning"
                    aria-hidden="true"
                  />
                  <span className="min-w-0 truncate">
                    <span className="font-medium text-brand-navy">
                      {source.name}
                    </span>{" "}
                    <span className="text-shell-muted">
                      {t.environment.twin.coverage.states[
                        source.state
                      ].toLowerCase()}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {uncovered.length && (env.sources ?? []).length > 0 ? (
            <p className="text-shell-muted">
              {fill(w.notCovered, {
                parts: uncovered.map((c) => parts[c.part]).join(", "),
              })}
            </p>
          ) : null}
        </div>
      )}
    </Card>
  );
}

// ── The page ───────────────────────────────────────────────────────────────

export function Overview() {
  const load = useOverviewData();

  // What needs someone first — a decision, something in trouble, a request
  // under way — then what moved and whether what LEKA sees can be trusted
  // (LEKA-442: docs/frontend/overview-and-twin.md says each card's question).
  return (
    <PageContainer>
      <Greeting load={load} />
      <div className="mt-5">
        <CompactIntentionComposer />
      </div>
      {load.status === "ready" ? (
        <FirstStepsCard sources={load.sources} />
      ) : null}
      <div
        className="mt-4 grid gap-4 xl:grid-cols-3"
        data-testid="overview-now"
      >
        <ApprovalsCard />
        <TroubleCard />
        <IntentionsCard />
      </div>
      <div
        className="mt-4 grid gap-4 xl:grid-cols-3"
        data-testid="overview-context"
      >
        <ActivityCard />
        <FreshnessCard />
        <InsightsCard />
      </div>
    </PageContainer>
  );
}
