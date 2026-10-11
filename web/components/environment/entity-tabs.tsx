"use client";

import {
  ArrowDown,
  ArrowUp,
  ExternalLink,
  FileText,
  GitCommitHorizontal,
  type LucideIcon,
  Rocket,
  Ticket,
  TriangleAlert,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { cn } from "cn";

import { Card, entityHref, eventRows, EventList, Logo } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { shortWhen, timeAgo } from "@/components/knowledge/time";
import { hasSourceLogo, sourceTitle } from "@/components/sources/source-logo";
import { ErrorState } from "@/components/states/error-state";
import { routes } from "@/config/routes";
import type { EntityActivity, EntityActivityEvent, EntitySheet } from "@/lib/environment";
import { useEntityActivity } from "@/lib/environment-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";

/**
 * An entity's tabs beyond its overview (mockup 11): what its sources show
 * of its life — LEKA reads no runtime logs nor metrics, it reads what moved:
 * changes, deployments, incidents, tickets, day by day, against the period
 * before (GET …/environment/{id}/activity). Its configuration, as its sources
 * say it and as LEKA deduces it. Every figure real; what needs a monitoring
 * tool, said so, with the way to connect one.
 */

export const PERIODS = [7, 30, 90] as const;
export type PeriodDays = (typeof PERIODS)[number];
type Bucket = "changes" | "deployments" | "incidents" | "work" | "other";
const BUCKETS: readonly Bucket[] = ["changes", "deployments", "incidents", "work", "other"];
const BUCKET_FILL: Record<Bucket, string> = {
  changes: "fill-shell-nav-active",
  deployments: "fill-state-success",
  incidents: "fill-state-danger",
  work: "fill-state-warning",
  other: "fill-shell-muted",
};
const BUCKET_DOT: Record<Bucket, string> = {
  changes: "bg-shell-nav-active",
  deployments: "bg-state-success",
  incidents: "bg-state-danger",
  work: "bg-state-warning",
  other: "bg-shell-muted",
};
const TYPE_ICON: Record<string, LucideIcon> = {
  commit: GitCommitHorizontal,
  pull_request: GitCommitHorizontal,
  release: Rocket,
  deployment: Rocket,
  incident: TriangleAlert,
  issue: Ticket,
  document: FileText,
};

export function bucketOf(event: EntityActivityEvent): Bucket {
  const type = event.entity.type;
  if (type === "commit" || type === "pull_request") return "changes";
  if (type === "deployment" || type === "release") return "deployments";
  if (type === "incident") return "incidents";
  if (type === "issue") return "work";
  return "other";
}

function sources(kinds: readonly string[], or: string): string {
  return kinds.map((k) => (hasSourceLogo(k) ? sourceTitle(k) : k)).join(or);
}

export function PeriodChoice({
  value,
  onChange,
}: {
  value: PeriodDays;
  onChange: (next: PeriodDays) => void;
}) {
  const t = useDictionary();
  const w = t.environment.sheet.activity;
  return (
    <div className="flex gap-1" role="group" aria-label={w.period}>
      {PERIODS.map((days) => (
        <button
          key={days}
          type="button"
          aria-pressed={value === days}
          onClick={() => onChange(days)}
          className={cn(
            "rounded-lg border px-2.5 py-1 text-xs font-medium",
            value === days
              ? "border-shell-nav-active bg-brand-violet-soft text-shell-nav-active"
              : "border-shell-line bg-white text-shell-muted hover:text-brand-navy",
          )}
        >
          {w.periods[String(days) as "7"]}
        </button>
      ))}
    </div>
  );
}

function Delta({ now, before, goodWhenDown = false }: { now: number; before: number; goodWhenDown?: boolean }) {
  if (!before && !now) return null;
  if (!before) {
    return <span className="text-xs font-medium text-shell-muted">+{now}</span>;
  }
  const change = Math.round(((now - before) / before) * 100);
  const up = change >= 0;
  const good = up !== goodWhenDown;
  const Arrow = up ? ArrowUp : ArrowDown;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-xs font-medium",
        good ? "text-state-success" : "text-state-danger",
      )}
    >
      {up ? "+" : ""}
      {change} %
      <Arrow className="size-3" aria-hidden="true" />
    </span>
  );
}

/** Four figures of its activity, each against the period before. */
export function ActivityTiles({ activity }: { activity: EntityActivity }) {
  const t = useDictionary();
  const w = t.environment.sheet.activity;
  const tiles: { key: Bucket; icon: LucideIcon; label: string; value: number; note: string; goodWhenDown?: boolean }[] = [
    { key: "changes", icon: GitCommitHorizontal, label: w.changes, value: activity.changes, note: w.changesNote },
    { key: "deployments", icon: Rocket, label: w.deployments, value: activity.deployments, note: w.deploymentsNote },
    {
      key: "incidents",
      icon: TriangleAlert,
      label: w.incidents,
      value: activity.incidents,
      note: fill(w.incidentsNote, { open: activity.incidents_open }),
      goodWhenDown: true,
    },
    { key: "work", icon: Ticket, label: w.work, value: activity.work, note: fill(w.workNote, { open: activity.work_open }) },
  ];
  return (
    <>
      {tiles.map((tile) => (
        <div
          key={tile.key}
          className="rounded-xl border border-shell-line bg-white p-4"
          data-testid={`activity-${tile.key}`}
        >
          <p className="flex items-center gap-2 text-[0.8125rem] text-brand-navy">
            <tile.icon className="size-4 text-shell-muted" aria-hidden="true" />
            {tile.label}
          </p>
          <p className="mt-2 text-[1.75rem] leading-8 font-bold text-brand-navy tabular-nums">{tile.value}</p>
          <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs text-shell-muted">{tile.note}</span>
            <Delta now={tile.value} before={activity.previous[tile.key] ?? 0} goodWhenDown={tile.goodWhenDown} />
          </div>
        </div>
      ))}
    </>
  );
}

const WIDTH = 640;
const HEIGHT = 170;
const BOTTOM = 20;

/** Day by day, stacked by kind, on one scale. */
export function ActivityChart({ activity }: { activity: EntityActivity }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.environment.sheet.activity;
  const totals = activity.by_day.map((d) => BUCKETS.reduce((sum, b) => sum + d[b], 0));
  const top = Math.max(4, ...totals);
  const slot = WIDTH / Math.max(1, activity.by_day.length);
  const bar = Math.max(2, Math.min(18, slot * 0.6));
  const plot = HEIGHT - BOTTOM;
  const every = Math.ceil(activity.by_day.length / 8);
  const day = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" });
  if (!totals.some(Boolean)) {
    return <p className="py-8 text-center text-[0.8125rem] text-shell-muted">{w.none}</p>;
  }
  return (
    <div data-testid="activity-chart">
      <ul className="mb-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-shell-muted">
        {BUCKETS.filter((b) => activity.by_day.some((d) => d[b])).map((b) => (
          <li key={b} className="flex items-center gap-1">
            <span className={cn("size-2 rounded-full", BUCKET_DOT[b])} />
            {w.legend[b]}
          </li>
        ))}
      </ul>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-auto w-full" role="img" aria-label={w.chart}>
        <line x1={0} x2={WIDTH} y1={plot} y2={plot} className="stroke-shell-line" />
        {activity.by_day.map((d, index) => {
          let y = plot;
          return (
            <g key={d.day}>
              {BUCKETS.map((b) => {
                if (!d[b]) return null;
                const height = (d[b] / top) * (plot - 6);
                y -= height;
                return (
                  <rect
                    key={b}
                    x={index * slot + (slot - bar) / 2}
                    y={y}
                    width={bar}
                    height={height}
                    rx={1.5}
                    className={BUCKET_FILL[b]}
                  />
                );
              })}
              {index % every === 0 ? (
                <text x={index * slot + slot / 2} y={HEIGHT - 5} textAnchor="middle" className="fill-shell-muted text-[10px]">
                  {day.format(new Date(`${d.day}T12:00:00Z`))}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function RuntimeNote({ activity }: { activity: EntityActivity }) {
  const t = useDictionary();
  const w = t.environment.sheet.activity;
  return (
    <p className="text-xs text-shell-muted" data-testid="runtime-note">
      {activity.log_sources.length
        ? fill(w.runtimeConnected, { sources: sources(activity.log_sources, t.catalogue.or) })
        : w.runtime}{" "}
      {activity.log_sources.length ? null : (
        <Link href={routes.sources()} className="font-medium text-shell-nav-active hover:underline">
          {w.connect}
        </Link>
      )}
    </p>
  );
}

function useActivity(entityId: string, days: PeriodDays) {
  return useEntityActivity(entityId, days);
}

function Loading() {
  return <div className="h-64 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
}

export function MetricsTab({ entityId }: { entityId: string }) {
  const t = useDictionary();
  const w = t.environment.sheet.activity;
  const [days, setDays] = useState<PeriodDays>(30);
  const query = useActivity(entityId, days);
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (!query.data) return <Loading />;
  const activity = query.data;
  return (
    <div className="flex flex-col gap-4" data-testid="metrics-tab">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <RuntimeNote activity={activity} />
        <PeriodChoice value={days} onChange={setDays} />
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <ActivityTiles activity={activity} />
      </div>
      <Card title={w.chart}>
        <ActivityChart activity={activity} />
        {activity.last_activity ? (
          <p className="mt-2 text-xs text-shell-muted">
            {fill(w.last, { when: timeAgo(t, activity.last_activity) })}
          </p>
        ) : null}
      </Card>
    </div>
  );
}

function EventLine({ event }: { event: EntityActivityEvent }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.environment.sheet.activity;
  const Icon = TYPE_ICON[event.entity.type] ?? FileText;
  const typeWord = (w.types as Record<string, string>)[event.entity.type] ?? event.entity.type;
  return (
    <li className="flex items-center gap-3 py-2 text-[0.8125rem]" data-testid="activity-event" data-bucket={bucketOf(event)}>
      <span className="w-16 shrink-0 whitespace-nowrap text-shell-muted tabular-nums">{shortWhen(locale, event.at)}</span>
      <Icon className="size-4 shrink-0 text-shell-muted" aria-hidden="true" />
      {event.source_kinds[0] ? <Logo kind={event.source_kinds[0]} className="size-4 shrink-0" /> : null}
      <span className="min-w-0 flex-1">
        <Link href={entityHref(event.entity)} className="block truncate font-medium text-brand-navy hover:underline">
          {event.entity.name}
        </Link>
        <span className="text-xs text-shell-muted">
          {typeWord}
          {event.version ? ` · ${event.version}` : ""}
          {event.environment ? ` · ${fill(w.environment, { environment: event.environment })}` : ""}
          {event.where ? ` · ${event.where.name}` : ""}
        </span>
      </span>
      {event.state ? <Pill tone={event.kind === "incident" ? "danger" : "neutral"}>{event.state}</Pill> : null}
      {event.url && /^https?:\/\//i.test(event.url) ? (
        <a href={event.url} target="_blank" rel="noreferrer" aria-label={w.open} className="text-shell-muted hover:text-shell-nav-active">
          <ExternalLink className="size-4" aria-hidden="true" />
        </a>
      ) : null}
    </li>
  );
}

export function DeploymentsTab({ entityId }: { entityId: string }) {
  const t = useDictionary();
  const w = t.environment.sheet.activity;
  const [days, setDays] = useState<PeriodDays>(90);
  const query = useActivity(entityId, days);
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (!query.data) return <Loading />;
  const deployments = query.data.events.filter((e) => bucketOf(e) === "deployments");
  return (
    <Card title={w.deploymentsTitle} action={<PeriodChoice value={days} onChange={setDays} />}>
      {deployments.length ? (
        <ul className="divide-y divide-shell-line/60" data-testid="deployments">
          {deployments.map((event) => (
            <EventLine key={event.entity.id} event={event} />
          ))}
        </ul>
      ) : (
        <p className="py-6 text-center text-[0.8125rem] text-shell-muted" data-testid="deployments-empty">
          {w.deploymentsEmpty}
        </p>
      )}
    </Card>
  );
}

export function LogsTab({ entityId }: { entityId: string }) {
  const t = useDictionary();
  const w = t.environment.sheet.activity;
  const [days, setDays] = useState<PeriodDays>(30);
  const [filter, setFilter] = useState<Bucket | "all">("all");
  const query = useActivity(entityId, days);
  const shown = useMemo(
    () => (query.data?.events ?? []).filter((e) => filter === "all" || bucketOf(e) === filter),
    [query.data, filter],
  );
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (!query.data) return <Loading />;
  const activity = query.data;
  return (
    <Card title={w.logsTitle} action={<PeriodChoice value={days} onChange={setDays} />}>
      <p className="mb-2 text-[0.8125rem] text-shell-muted">
        {w.logsBody}{" "}
        {activity.log_sources.length
          ? fill(w.logsRuntime, { sources: sources(activity.log_sources, t.catalogue.or) })
          : null}
      </p>
      <div className="mb-2 flex flex-wrap gap-1.5" role="group" aria-label={w.logsTitle}>
        {(["all", ...BUCKETS] as const).map((name) => (
          <button
            key={name}
            type="button"
            aria-pressed={filter === name}
            onClick={() => setFilter(name)}
            data-testid={`logs-filter-${name}`}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium",
              filter === name
                ? "border-shell-nav-active bg-brand-violet-soft text-shell-nav-active"
                : "border-shell-line bg-white text-shell-nav hover:bg-shell-canvas",
            )}
          >
            {w.filters[name]}
          </button>
        ))}
      </div>
      {shown.length ? (
        <ul className="divide-y divide-shell-line/60" data-testid="logs">
          {shown.map((event) => (
            <EventLine key={event.entity.id} event={event} />
          ))}
        </ul>
      ) : (
        <p className="py-6 text-center text-[0.8125rem] text-shell-muted">{w.logsEmpty}</p>
      )}
      {activity.log_sources.length ? null : <div className="mt-3"><RuntimeNote activity={activity} /></div>}
    </Card>
  );
}

/** A value as people read it. */
function valueSaid(value: unknown, locale: string): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "✓" : "✗";
  if (typeof value === "number") return new Intl.NumberFormat(locale).format(value);
  if (typeof value === "string") {
    if (/^\d{4}-\d{2}-\d{2}T/.test(value)) {
      const at = new Date(value);
      if (!Number.isNaN(at.getTime())) {
        return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(at);
      }
    }
    return value;
  }
  if (Array.isArray(value)) return value.map((v) => valueSaid(v, locale)).join(", ");
  return Object.entries(value as Record<string, unknown>)
    .map(([k, v]) => `${k}: ${valueSaid(v, locale)}`)
    .join(" · ");
}

// What the sources say that is not configuration: how it is found, linked.
const NOT_CONFIGURATION = new Set(["url", "description"]);

export function ConfigurationTab({ sheet }: { sheet: EntitySheet }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.environment.sheet.activity;
  const entity = sheet.entity;
  const stated = Object.entries(entity.attributes ?? {})
    .filter(([name, value]) => !NOT_CONFIGURATION.has(name) && value !== null && value !== "")
    .sort(([a], [b]) => a.localeCompare(b));
  return (
    <div className="grid gap-4 xl:grid-cols-2" data-testid="configuration-tab">
      <Card title={w.configurationStated}>
        <dl className="grid grid-cols-[minmax(0,11rem)_minmax(0,1fr)] gap-x-3 gap-y-2 text-[0.8125rem]">
          <dt className="text-shell-muted">{w.key}</dt>
          <dd className="font-mono text-xs break-all text-brand-navy">{entity.key}</dd>
          <dt className="text-shell-muted">{w.sources}</dt>
          <dd className="flex flex-wrap gap-1.5">
            {sheet.source_kinds.map((kind) => (
              <Logo key={kind} kind={kind} className="size-4" />
            ))}
          </dd>
          {stated.map(([name, value]) => (
            <div key={name} className="contents" data-testid="configuration-stated">
              <dt className="truncate text-shell-muted" title={name}>
                {name}
              </dt>
              <dd className="break-words text-brand-navy">{valueSaid(value, locale)}</dd>
            </div>
          ))}
        </dl>
        {stated.length === 0 ? (
          <p className="mt-2 text-[0.8125rem] text-shell-muted">{w.configurationStatedEmpty}</p>
        ) : null}
      </Card>
      <Card title={w.configurationDeduced}>
        {entity.enriched.length ? (
          <ul className="space-y-2 text-[0.8125rem]">
            {entity.enriched.map((attribute) => (
              <li key={attribute.attribute} className="flex flex-col" data-testid="configuration-deduced">
                <span className="text-shell-muted">{attribute.attribute}</span>
                <span className="text-brand-navy">{valueSaid(attribute.value, locale)}</span>
                <span className="text-xs text-shell-muted">
                  {attribute.evidence || attribute.rule}
                  {` · ${fill(w.confidence, { score: Math.round(attribute.confidence * 100) })}`}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[0.8125rem] text-shell-muted">{w.configurationDeducedEmpty}</p>
        )}
      </Card>
    </div>
  );
}

/** What else the incidents tab says: the tickets open around it. */
export function OpenWork({ entityId }: { entityId: string }) {
  const t = useDictionary();
  const w = t.environment.sheet.activity;
  const query = useActivity(entityId, 90);
  if (!query.data) return null;
  const open = query.data.events.filter(
    (e) => bucketOf(e) === "work" && ["open", "in_progress"].includes(e.state ?? ""),
  );
  return (
    <Card title={w.workOpen}>
      {open.length ? (
        <ul className="divide-y divide-shell-line/60" data-testid="open-work">
          {open.map((event) => (
            <EventLine key={event.entity.id} event={event} />
          ))}
        </ul>
      ) : (
        <p className="py-4 text-center text-[0.8125rem] text-shell-muted">{w.workOpenEmpty}</p>
      )}
    </Card>
  );
}

/** Documents that name it, not linked yet as its documentation. */
export function Mentions({ entityId }: { entityId: string }) {
  const t = useDictionary();
  const w = t.environment.sheet.activity;
  const query = useActivity(entityId, 30);
  if (!query.data) return null;
  return (
    <Card title={w.mentions}>
      {query.data.mentions.length ? (
        <ul className="space-y-2 text-[0.8125rem]" data-testid="mentions">
          {query.data.mentions.map((document) => (
            <li key={document.id} className="flex items-center gap-2">
              <FileText className="size-4 text-shell-muted" aria-hidden="true" />
              <Link href={entityHref(document)} className="truncate font-medium text-brand-navy hover:underline">
                {document.name}
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[0.8125rem] text-shell-muted">{w.mentionsEmpty}</p>
      )}
    </Card>
  );
}

/** Its incidents, as the sheet holds them. */
export function IncidentsList({ sheet, empty }: { sheet: EntitySheet; empty: string }) {
  const t = useDictionary();
  return <EventList rows={eventRows(t, sheet.incidents)} empty={empty} detailed />;
}

/** The overview's four tiles: the last 30 days of its activity. */
export function OverviewTiles({ entityId, days }: { entityId: string; days: PeriodDays }) {
  const query = useActivity(entityId, days);
  if (!query.data) {
    return (
      <>
        {[0, 1, 2, 3].map((n) => (
          <div key={n} className="h-28 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />
        ))}
      </>
    );
  }
  return <ActivityTiles activity={query.data} />;
}

/** The overview's chart: its activity day by day — what monitoring would
 * add, said, with the way to connect it. */
export function ActivityCard({ entityId, days }: { entityId: string; days: PeriodDays }) {
  const t = useDictionary();
  const w = t.environment.sheet.activity;
  const query = useActivity(entityId, days);
  return (
    <Card title={w.chart}>
      {query.data ? (
        <>
          <ActivityChart activity={query.data} />
          <div className="mt-2">
            <RuntimeNote activity={query.data} />
          </div>
        </>
      ) : (
        <div className="h-40 animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />
      )}
    </Card>
  );
}
