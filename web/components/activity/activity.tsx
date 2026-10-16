"use client";

import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  CalendarDays,
  CircleAlert,
  CircleCheck,
  ClipboardCheck,
  Cog,
  Download,
  Ellipsis,
  FileText,
  History,
  Lightbulb,
  ListChecks,
  type LucideIcon,
  PackageMinus,
  RefreshCw,
  Rocket,
  RotateCcw,
  Scale,
  Sparkles,
  Tag,
  TriangleAlert,
  Undo2,
  Users,
  Waypoints,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { cn } from "cn";
import { byWho, delta, personName, toCsv, wordActivity } from "@/components/activity/items";
import { CATEGORY_DOT, columns, Donut, StackedBars } from "@/components/activity/charts";
import { IconTile, type TileTone, typeIcon } from "@/components/environment/parts";
import { hrefOf, word } from "@/components/insights/leka-insights";
import { shortWhen } from "@/components/knowledge/time";
import { BackHome, PageContainer } from "@/components/shell/page-container";
import { StatCard, StatGrid } from "@/components/shell/stat-card";
import { usePermissions } from "@/components/shell/shell-provider";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { routes } from "@/config/routes";
import {
  type Activity,
  type ActivityCategory,
  type ActivityCount,
  type ActivityItem,
  CATEGORIES,
  PERIODS,
  type PeriodDays,
} from "@/lib/activity";
import { typeSegment } from "@/lib/environment";
import { useActivity, useOperations, useTrends } from "@/lib/evolution-queries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

/**
 * Activité, laid out as docs/product/mockups/08-activite.jpeg (LEKA-383):
 * what happened in the environment and what LEKA did over a period —
 * every figure real, read from the model's history, the systems' events,
 * the analyses and the decisions (GET /intelligence/activity). Its
 * insights are those of the model's course: the bottom banner names them.
 */

const SHOWN = 8;
const ALL = 50;
const ORIGINS = ["leka", "person", "policy", "source"] as const;
type Origin = (typeof ORIGINS)[number];

export const KIND_ICON: Record<ActivityItem["kind"], LucideIcon> = {
  model_built: RefreshCw,
  entity_removed: PackageMinus,
  incident: TriangleAlert,
  deployment: Rocket,
  change: FileText,
  release: Tag,
  analysis: Cog,
  finding: Lightbulb,
  proposal: Sparkles,
  decision: CircleCheck,
  conflict: Scale,
  conflict_decision: Scale,
  restore: History,
  rebuild: RotateCcw,
  undo: Undo2,
  source_event: Waypoints,
};

export const CATEGORY_TONE: Record<ActivityCategory, TileTone> = {
  information: "info",
  action: "success",
  alert: "warning",
  incident: "danger",
};

export const CHIP: Record<ActivityCategory, string> = {
  information: "bg-state-info-soft text-state-info",
  action: "bg-state-success-soft text-state-success",
  alert: "bg-state-warning-soft text-state-warning",
  incident: "bg-state-danger-soft text-state-danger",
};

export function ActivityScreen() {
  const t = useDictionary();
  const w = t.activity;
  const [days, setDays] = useState<PeriodDays>(7);
  const [category, setCategory] = useState<ActivityCategory | "all">("all");
  const [origin, setOrigin] = useState<Origin | "all">("all");
  const activity = useActivity(days);
  const data = activity.data;
  const latest = useMemo(
    () =>
      (data?.latest ?? []).filter(
        (item) =>
          (category === "all" || item.category === category) &&
          (origin === "all" || item.via === origin),
      ),
    [data, category, origin],
  );

  function exportCsv() {
    const blob = new Blob([`\uFEFF${toCsv(t, latest)}`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `leka-activite-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <PageContainer>
      <BackHome />
      <div className="mb-5 flex flex-col gap-4 2xl:flex-row 2xl:items-start">
        <div className="min-w-0 flex-1">
          <h1 className="text-[2.125rem] leading-tight font-bold tracking-[-0.02em] text-brand-navy">
            {w.title}
          </h1>
          <p className="mt-1 text-[1.0625rem] text-shell-accent-muted">{w.subtitle}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Choice
            label={w.period}
            icon={CalendarDays}
            value={String(days)}
            onChange={(value) => setDays(Number(value) as PeriodDays)}
            options={PERIODS.map((value) => ({
              value: String(value),
              label: w.periods[String(value) as "7"],
            }))}
          />
          <Choice
            label={w.type}
            value={category}
            onChange={(value) => setCategory(value as ActivityCategory | "all")}
            options={[
              { value: "all", label: w.allTypes },
              ...CATEGORIES.map((value) => ({ value, label: w.categories[value] })),
            ]}
          />
          <Choice
            label={w.origin}
            value={origin}
            onChange={(value) => setOrigin(value as Origin | "all")}
            options={[
              { value: "all", label: w.allOrigins },
              ...ORIGINS.map((value) => ({ value, label: w.origins[value] })),
            ]}
          />
          <button
            type="button"
            onClick={exportCsv}
            disabled={!latest.length}
            className="flex h-9 items-center gap-2 rounded-lg border border-shell-line bg-white px-3 text-sm font-medium text-brand-navy outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-brand-violet/40 disabled:opacity-60"
          >
            <Download className="size-4" aria-hidden="true" />
            {w.export}
          </button>
          <Rebuild />
        </div>
      </div>

      {activity.isError ? (
        <p className="rounded-xl border border-shell-line bg-white p-4 text-sm text-shell-muted" role="alert">
          {w.failed}{" "}
          <button
            type="button"
            onClick={() => void activity.refetch()}
            className="font-medium text-shell-nav-active underline-offset-2 hover:underline"
          >
            {w.retry}
          </button>
        </p>
      ) : !data ? (
        <div className="h-96 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />
      ) : (
        <>
          <Stats data={data} />
          <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <div className="flex min-w-0 flex-col gap-4">
              <Chart data={data} days={days} />
              <Latest items={latest} />
            </div>
            <div className="flex min-w-0 flex-col gap-4">
              <Split data={data} />
              <Top data={data} />
              <People data={data} />
            </div>
          </div>
          <Trends />
        </>
      )}
    </PageContainer>
  );
}

function Choice({
  label,
  icon: Icon,
  value,
  onChange,
  options,
}: {
  label: string;
  icon?: LucideIcon;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <Select value={value} onValueChange={(next) => onChange(String(next ?? value))} items={options}>
      <SelectTrigger className="min-w-40 bg-white" aria-label={label}>
        {Icon ? <Icon className="size-4 text-shell-muted" aria-hidden="true" /> : null}
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Rebuild the model — for who may decide what it says. */
function Rebuild() {
  const t = useDictionary();
  const permissions = usePermissions();
  const { rebuild } = useOperations();
  if (!permissions?.includes("intention:approve")) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={t.activity.more}
        className="flex size-9 items-center justify-center rounded-lg border border-shell-line bg-white text-brand-navy outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-brand-violet/40"
      >
        <Ellipsis className="size-4" aria-hidden="true" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuItem
          onClick={() =>
            rebuild.mutate(
              {},
              {
                onSuccess: () => notify.success({ title: t.activity.rebuilt }),
                onError: () => notify.error({ title: t.activity.rebuildFailed }),
              },
            )
          }
        >
          <RotateCcw className="size-4" aria-hidden="true" />
          {t.activity.rebuild}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function Delta({
  count,
  goodWhenDown = false,
}: {
  count: ActivityCount;
  goodWhenDown?: boolean;
}) {
  const t = useDictionary();
  const said = delta(count);
  if (!said) return <span className="h-4" />;
  const good = said.up !== goodWhenDown;
  const Arrow = said.up ? ArrowUp : ArrowDown;
  return (
    <span
      className={cn(
        "flex items-center gap-1 text-xs font-medium",
        good ? "text-state-success" : "text-state-danger",
      )}
      title={t.activity.stats.versus}
    >
      {said.text}
      <Arrow className="size-3.5" aria-hidden="true" />
      <span className="sr-only">{t.activity.stats.versus}</span>
    </span>
  );
}

function Stats({ data }: { data: Activity }) {
  const t = useDictionary();
  const s = t.activity.stats;
  const all: {
    key: string;
    icon: LucideIcon;
    tone: TileTone;
    value: number;
    label: string;
    foot: React.ReactNode;
    href?: string;
  }[] = [
    {
      key: "events",
      icon: ListChecks,
      tone: "violet",
      value: data.stats.events.value,
      label: s.events,
      foot: <Delta count={data.stats.events} />,
    },
    {
      key: "actions",
      icon: CircleCheck,
      tone: "success",
      value: data.stats.actions.value,
      label: s.actions,
      foot: <Delta count={data.stats.actions} />,
    },
    {
      key: "incidents",
      icon: TriangleAlert,
      tone: "warning",
      value: data.stats.incidents.value,
      label: s.incidents,
      foot: <Delta count={data.stats.incidents} goodWhenDown />,
    },
    {
      key: "waiting",
      icon: ClipboardCheck,
      tone: "warning",
      value: data.stats.waiting,
      label: s.waiting,
      foot: <span className="text-xs leading-4 text-shell-muted">{s.waitingNote}</span>,
      href: routes.approvals(),
    },
    {
      key: "people",
      icon: Users,
      tone: "violet",
      value: data.stats.people.value,
      label: s.people,
      foot: <Delta count={data.stats.people} />,
    },
  ];
  // Nobody active over the period: a 0 that calls for nothing (LEKA-438).
  const tiles = all.filter((tile) => tile.key !== "people" || tile.value > 0);
  return (
    <StatGrid count={tiles.length} testId="activity-stats">
      {tiles.map((tile) => (
        <StatCard
          key={tile.key}
          icon={tile.icon}
          tone={tile.tone}
          value={tile.value}
          label={tile.label}
          foot={tile.foot}
          href={tile.href}
          valueTestId={`activity-stat-${tile.key}`}
        />
      ))}
    </StatGrid>
  );
}

function Section({
  title,
  action,
  children,
  className,
  testId,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  testId?: string;
}) {
  return (
    <section
      className={cn("rounded-xl border border-shell-line bg-white p-4", className)}
      data-testid={testId}
    >
      <div className="mb-3 flex items-center gap-3">
        <h2 className="flex-1 text-[1.0625rem] font-semibold tracking-[-0.01em] text-brand-navy">
          {title}
        </h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Legend() {
  const t = useDictionary();
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-shell-muted">
      {CATEGORIES.map((category) => (
        <li key={category} className="flex items-center gap-1.5">
          <span className={cn("size-2.5 rounded-sm", CATEGORY_DOT[category])} aria-hidden="true" />
          {t.activity.categories[category]}
        </li>
      ))}
    </ul>
  );
}

function Chart({ data, days }: { data: Activity; days: PeriodDays }) {
  const t = useDictionary();
  const c = t.activity.chart;
  const [unit, setUnit] = useState<"day" | "week" | null>(null);
  const byWeek = (unit ?? (days > 30 ? "week" : "day")) === "week";
  const drawn = columns(data.buckets, byWeek);
  const empty = data.stats.events.value === 0;
  return (
    <Section
      title={c.title}
      testId="activity-chart"
      action={
        <Choice
          label={c.unit}
          value={byWeek ? "week" : "day"}
          onChange={(value) => setUnit(value as "day" | "week")}
          options={[
            { value: "day", label: c.byDay },
            { value: "week", label: c.byWeek },
          ]}
        />
      }
    >
      <Legend />
      {empty ? (
        <p className="py-10 text-center text-sm text-shell-muted">{c.empty}</p>
      ) : (
        <StackedBars data={drawn} className="mt-3" />
      )}
    </Section>
  );
}

function Split({ data }: { data: Activity }) {
  const t = useDictionary();
  const counts = Object.fromEntries(
    CATEGORIES.map((category) => [category, data.categories[category] ?? 0]),
  ) as Record<ActivityCategory, number>;
  const sum = CATEGORIES.reduce((s, c) => s + counts[c], 0);
  return (
    <Section title={t.activity.split.title} testId="activity-split">
      <div className="flex flex-wrap items-center gap-5">
        <Donut counts={counts} />
        <ul className="min-w-40 flex-1 space-y-2 text-[0.8125rem]">
          {CATEGORIES.map((category) => (
            <li key={category} className="flex items-center gap-2">
              <span
                className={cn("size-3 rounded-full", CATEGORY_DOT[category])}
                aria-hidden="true"
              />
              <span className="flex-1 text-brand-navy">{t.activity.categories[category]}</span>
              <span className="font-medium text-brand-navy tabular-nums">
                {sum ? Math.round((counts[category] / sum) * 100) : 0} %
              </span>
            </li>
          ))}
        </ul>
      </div>
    </Section>
  );
}

function Latest({ items }: { items: readonly ActivityItem[] }) {
  const t = useDictionary();
  const w = t.activity.latest;
  const { format: locale } = useLocale();
  const [all, setAll] = useState(false);
  const shown = items.slice(0, all ? ALL : SHOWN);
  return (
    <Section
      title={w.title}
      testId="activity-latest"
      action={
        items.length > SHOWN ? (
          <button
            type="button"
            onClick={() => setAll(!all)}
            className="flex items-center gap-1 rounded text-[0.8125rem] font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          >
            {all ? w.fewer : w.all}
            <ArrowRight className="rtl:-scale-x-100 size-3.5" aria-hidden="true" />
          </button>
        ) : null
      }
    >
      {shown.length ? (
        <ul className="divide-y divide-shell-line/60">
          {shown.map((item) => {
            const worded = wordActivity(t, item);
            const who = byWho(t, item);
            const row = (
              <>
                <span className="w-14 shrink-0 text-xs text-shell-muted tabular-nums">
                  {shortWhen(locale, item.at)}
                </span>
                <span
                  className={cn("size-2 shrink-0 rounded-full", CATEGORY_DOT[item.category])}
                  aria-hidden="true"
                />
                <IconTile
                  icon={KIND_ICON[item.kind] ?? CircleAlert}
                  tone={CATEGORY_TONE[item.category]}
                  className="size-9"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[0.8125rem] font-semibold text-brand-navy">
                    {worded.title}
                  </span>
                  <span className="block truncate text-xs text-shell-muted">
                    {[worded.detail, who].filter(Boolean).join(" · ")}
                  </span>
                </span>
                <span
                  className={cn(
                    "hidden shrink-0 rounded-md px-2 py-0.5 text-xs font-medium sm:inline",
                    CHIP[item.category],
                  )}
                >
                  {t.activity.category[item.category]}
                </span>
                {item.subject && item.subject.type === "entity" ? (
                  <span className="hidden max-w-36 shrink-0 truncate rounded-md border border-shell-line px-2 py-0.5 text-xs text-brand-navy md:inline">
                    {item.subject.name}
                  </span>
                ) : null}
                {worded.href ? (
                  <ArrowRight className="rtl:-scale-x-100 size-4 shrink-0 text-shell-muted" aria-hidden="true" />
                ) : (
                  <span className="size-4 shrink-0" />
                )}
              </>
            );
            return (
              <li key={item.id} data-testid={`activity-item-${item.kind}`}>
                {worded.href ? (
                  <Link
                    href={worded.href}
                    className="-mx-1.5 flex items-center gap-3 rounded-lg px-1.5 py-2.5 outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-brand-violet/40"
                  >
                    {row}
                  </Link>
                ) : (
                  <div className="flex items-center gap-3 py-2.5">{row}</div>
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="py-6 text-center text-sm text-shell-muted">{w.empty}</p>
      )}
    </Section>
  );
}

function Top({ data }: { data: Activity }) {
  const t = useDictionary();
  return (
    <Section title={t.activity.top.title} testId="activity-top">
      {data.top.length ? (
        <ul className="space-y-1">
          {data.top.map((top) => {
            const subject = top.subject;
            const href =
              subject.id && subject.kind ? routes.entity(typeSegment(subject.kind), subject.id) : null;
            const row = (
              <>
                <IconTile icon={typeIcon(subject.kind ?? "service")} tone="violet" className="size-8" />
                <span className="min-w-0 flex-1 truncate text-[0.8125rem] font-medium text-brand-navy">
                  {subject.name}
                </span>
                <span className="w-8 text-end text-[0.8125rem] text-brand-navy tabular-nums">
                  {top.count}
                </span>
                <span className="w-16 text-end">
                  <Delta count={{ value: top.count, previous: top.previous }} />
                </span>
              </>
            );
            return (
              <li key={subject.id ?? subject.name}>
                {href ? (
                  <Link
                    href={href}
                    className="-mx-1.5 flex items-center gap-3 rounded-lg px-1.5 py-1.5 outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-brand-violet/40"
                  >
                    {row}
                  </Link>
                ) : (
                  <div className="flex items-center gap-3 py-1.5">{row}</div>
                )}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="py-4 text-sm text-shell-muted">{t.activity.top.empty}</p>
      )}
    </Section>
  );
}

function People({ data }: { data: Activity }) {
  const t = useDictionary();
  const roles = t.shell.roles as Record<string, string>;
  return (
    <Section
      title={t.activity.people.title}
      testId="activity-people"
      action={
        <Link
          href={routes.team()}
          className="flex items-center gap-1 rounded text-[0.8125rem] font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        >
          {t.activity.people.team}
          <ArrowRight className="rtl:-scale-x-100 size-3.5" aria-hidden="true" />
        </Link>
      }
    >
      {data.people.length ? (
        <ul className="space-y-2">
          {data.people.map((person) => (
            <li key={person.user_id} className="flex items-center gap-3">
              <span
                className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-navy text-xs font-semibold text-white"
                aria-hidden="true"
              >
                {personName(person.name).slice(0, 1).toUpperCase()}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[0.8125rem] font-medium text-brand-navy">
                  {personName(person.name)}
                </span>
                {person.role ? (
                  <span className="block text-xs text-shell-muted">
                    {roles[person.role] ?? person.role}
                  </span>
                ) : null}
              </span>
              <span className="w-8 text-end text-[0.8125rem] text-brand-navy tabular-nums">
                {person.count}
              </span>
              <span className="w-16 text-end">
                <Delta count={{ value: person.count, previous: person.previous }} />
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="py-4 text-sm text-shell-muted">{t.activity.people.empty}</p>
      )}
    </Section>
  );
}

/** What LEKA reads in the model's course — its evolution insights. Said
 * when there are some; no banner, no second primary button (LEKA-438). */
function Trends() {
  const t = useDictionary();
  const w = t.activity.trends;
  const trends = useTrends();
  const found = trends.data?.data ?? [];
  if (!found.length) return null;
  return (
    <section
      className="mt-4 flex gap-4 rounded-xl border border-shell-line bg-white p-5"
      data-testid="activity-trends"
    >
      <Sparkles className="size-6 shrink-0 text-shell-nav-active" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <h2 className="text-[1.0625rem] font-semibold text-brand-navy">{w.title}</h2>
        <p className="text-[0.8125rem] text-shell-muted">{w.body}</p>
        <ul className="mt-2 space-y-1">
          {found.map((finding) => {
            const worded = word(t, finding);
            const href = hrefOf(finding);
            const line = (
              <>
                <span className="font-medium text-brand-navy">{worded.title}</span>
                {worded.detail ? (
                  <span className="text-shell-muted"> · {worded.detail}</span>
                ) : null}
              </>
            );
            return (
              <li key={finding.id} className="text-[0.8125rem]" data-testid="activity-trend">
                {href ? (
                  <Link href={href} className="rounded outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40">
                    {line}
                  </Link>
                ) : (
                  line
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}
