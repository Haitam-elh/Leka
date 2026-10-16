"use client";

import { Gauge, TrendingDown, TrendingUp } from "lucide-react";
import Link from "next/link";
import { useId, useMemo, useState } from "react";

import { cn } from "cn";

import { Card, entityHref, IconTile, type TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { KnowledgeTable, type KnowledgeColumn } from "@/components/knowledge/knowledge-table";
import { timeAgo } from "@/components/knowledge/time";
import { ErrorState } from "@/components/states/error-state";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import {
  DIMENSIONS,
  lacksOf,
  type QualityDetail,
  type QualityLevel,
  type QualityPoint,
  type QualityScore,
} from "@/lib/knowledge-quality";
import { useEntityQuality, useQualitySummary, useWeakest } from "@/lib/knowledge-quality-queries";

/**
 * Knowledge quality (LEKA-381): how far what LEKA knows can be trusted —
 * Mon environnement's tab Qualité, and a card on each thing's sheet.
 *
 * Every figure is the API's (GET /intelligence/quality…), measured by the
 * `quality` analysis on four dimensions (docs/intelligence.md § 15). A
 * dimension nothing measured says so, never a made-up 0 or 100; before any
 * measure, the screen says when there will be one. A level is always said
 * in words beside its colour.
 */

type Dictionary = ReturnType<typeof useDictionary>;

export const LEVEL_TONES: Record<QualityLevel, TileTone> = {
  high: "success",
  medium: "warning",
  low: "danger",
};
const BAR: Record<QualityLevel, string> = {
  high: "bg-state-success",
  medium: "bg-state-warning",
  low: "bg-state-danger",
};
const AREAS = ["columns", "teams", "applications"] as const;
type Area = (typeof AREAS)[number];

const pct = (value: number) => Math.round(value * 100);

function levelOf(score: number): QualityLevel {
  return score >= 0.85 ? "high" : score >= 0.6 ? "medium" : "low";
}

/** What lowers a score, in words: a thing's heaviest lacks — one of a
 * kind said once, with how many (two disagreements: "(2)") — an area's
 * most frequent, with how many things. */
export function lacksSaid(t: Dictionary, score: QualityScore, max = 2): string[] {
  const words = t.insights.quality.missing as Record<string, string>;
  const counted = new Map<string, number>();
  for (const lack of lacksOf(score)) {
    if (!words[lack.code]) continue;
    counted.set(lack.code, (counted.get(lack.code) ?? 0) + (lack.count ?? 1));
  }
  return [...counted]
    .slice(0, max)
    .map(([code, count]) => (count > 1 ? `${words[code]} (${count})` : words[code]));
}

function subjectName(t: Dictionary, score: QualityScore): string {
  if (score.scope === "workspace") return t.knowledgeQuality.workspace;
  if (score.scope === "column") {
    const columns = t.knowledgeQuality.columns as Record<string, string>;
    return columns[score.subject.name] ?? score.subject.name;
  }
  return score.subject.name;
}

function hrefOf(score: QualityScore): string | null {
  const { id, kind, type } = score.subject;
  return type === "entity" && id && kind ? entityHref({ id, type: kind }) : null;
}

// ── small parts ─────────────────────────────────────────────────────────

export function LevelPill({ level }: { level: QualityLevel }) {
  const t = useDictionary();
  return (
    <Pill tone={LEVEL_TONES[level]} dot data-testid="quality-level" data-level={level}>
      {t.knowledgeQuality.levels[level]}
    </Pill>
  );
}

/** A score as a bar and its value — "Non mesurée" when nothing measured it. */
function ScoreBar({ value, label }: { value: number | null | undefined; label?: string }) {
  const t = useDictionary();
  const known = value !== null && value !== undefined;
  return (
    <span className="flex min-w-0 items-center gap-2">
      <span
        className="h-1.5 min-w-12 flex-1 overflow-hidden rounded-full bg-shell-canvas"
        aria-hidden="true"
      >
        {known ? (
          <span
            className={cn("block h-full rounded-full", BAR[levelOf(value)])}
            style={{ width: `${pct(value)}%` }}
          />
        ) : null}
      </span>
      <span
        className="w-20 shrink-0 text-end text-[0.8125rem] font-medium text-brand-navy tabular-nums"
        aria-label={label}
      >
        {known ? `${pct(value)} %` : t.knowledgeQuality.unknown}
      </span>
    </span>
  );
}

function Dimensions({ score }: { score: QualityScore }) {
  const t = useDictionary();
  const w = t.knowledgeQuality.dimensions;
  return (
    <dl className="space-y-2" data-testid="quality-dimensions">
      {DIMENSIONS.map((name) => (
        <div key={name} className="grid grid-cols-[7rem_minmax(0,1fr)] items-center gap-x-3">
          <dt className="text-[0.8125rem] text-shell-muted">{w[name]}</dt>
          <dd data-testid={`quality-dimension-${name}`}>
            <ScoreBar value={score[name]} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

// ── the trend ───────────────────────────────────────────────────────────

const WIDTH = 600;
const HEIGHT = 140;
const PAD = { top: 10, bottom: 18, left: 0, right: 0 };
const DAY = 86_400_000;

/**
 * The workspace's score over 30 days, as the history keeps it: a point
 * each time it moved, held until the next — a step line. One series: the
 * title names it. Hover or arrow keys read each point; the list under it
 * says them all to a screen reader.
 */
export function QualityTrend({
  points,
  now = Date.now(),
}: {
  points: readonly QualityPoint[];
  now?: number;
}) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.knowledgeQuality.trend;
  const id = useId();
  const [active, setActive] = useState<number | null>(null);
  const start = now - 30 * DAY;

  const steps = useMemo(
    () =>
      points.map((point) => ({
        at: Math.max(start, new Date(point.measured_at).getTime()),
        score: point.score,
        point,
      })),
    [points, start],
  );
  if (steps.length < 2) {
    return (
      <p className="text-[0.8125rem] text-shell-muted" data-testid="quality-trend-empty">
        {w.empty}
      </p>
    );
  }

  const x = (at: number) =>
    PAD.left + ((at - start) / (now - start)) * (WIDTH - PAD.left - PAD.right);
  const y = (score: number) => PAD.top + (1 - score) * (HEIGHT - PAD.top - PAD.bottom);
  let path = `M ${x(steps[0].at)} ${y(steps[0].score)}`;
  for (const step of steps.slice(1)) path += ` H ${x(step.at)} V ${y(step.score)}`;
  path += ` H ${x(now)}`;

  const shown = active === null ? null : steps[active];
  const date = (at: number) =>
    new Date(at).toLocaleDateString(locale, { day: "numeric", month: "short" });

  function nearest(clientX: number, box: DOMRect) {
    const at = start + ((clientX - box.left) / box.width) * (now - start);
    // The step holding that moment: the last point at or before it.
    let found = 0;
    steps.forEach((step, index) => {
      if (step.at <= at) found = index;
    });
    setActive(found);
  }

  return (
    <figure className="relative" data-testid="quality-trend">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        className="h-36 w-full touch-none outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        role="img"
        aria-labelledby={`${id}-label`}
        tabIndex={0}
        onPointerMove={(event) =>
          nearest(event.clientX, event.currentTarget.getBoundingClientRect())
        }
        onPointerLeave={() => setActive(null)}
        onBlur={() => setActive(null)}
        onFocus={() => setActive(steps.length - 1)}
        onKeyDown={(event) => {
          if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
          event.preventDefault();
          const step = event.key === "ArrowLeft" ? -1 : 1;
          setActive((index) =>
            Math.min(steps.length - 1, Math.max(0, (index ?? steps.length - 1) + step)),
          );
        }}
      >
        <title id={`${id}-label`}>{w.label}</title>
        {/* The two thresholds, hairlines: reliable from 85, to consolidate from 60. */}
        {([0.85, 0.6] as const).map((line) => (
          <line
            key={line}
            x1={0}
            x2={WIDTH}
            y1={y(line)}
            y2={y(line)}
            className="stroke-shell-line"
            strokeWidth={1}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        <path
          d={path}
          fill="none"
          className="stroke-brand-violet"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
        {shown ? (
          <line
            x1={x(shown.at)}
            x2={x(shown.at)}
            y1={PAD.top}
            y2={HEIGHT - PAD.bottom}
            className="stroke-shell-muted"
            strokeWidth={1}
            vectorEffect="non-scaling-stroke"
          />
        ) : null}
      </svg>
      {shown ? (
        <div
          className="pointer-events-none absolute -top-2 rounded-md border border-shell-line bg-white px-2 py-1 text-xs shadow-sm"
          style={{
            left: `clamp(0px, calc(${(x(shown.at) / WIDTH) * 100}% - 3rem), calc(100% - 6rem))`,
          }}
          role="status"
          data-testid="quality-trend-tooltip"
        >
          <span className="font-semibold text-brand-navy tabular-nums">
            {pct(shown.score)} %
          </span>{" "}
          <span className="text-shell-muted">{date(shown.at)}</span>
        </div>
      ) : null}
      <figcaption className="mt-1 flex justify-between gap-3 text-[0.6875rem] text-shell-muted">
        <span>{date(start)}</span>
        <span>{w.thresholds}</span>
        <span>{date(now)}</span>
      </figcaption>
      <ul className="sr-only">
        {steps.map((step) => (
          <li key={step.point.measured_at}>
            {fill(w.at, { date: date(step.at), score: pct(step.score) })}
          </li>
        ))}
      </ul>
    </figure>
  );
}

// ── the tab ─────────────────────────────────────────────────────────────

function Headline({
  score,
  change,
  levels,
  trend,
}: {
  score: QualityScore;
  change: number | null;
  levels: Record<string, number>;
  trend: readonly QualityPoint[];
}) {
  const t = useDictionary();
  const w = t.knowledgeQuality;
  const points = change === null ? null : Math.round(change * 100);
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)_minmax(0,1.3fr)]">
      <Card
        title={w.workspace}
        icon={<IconTile icon={Gauge} tone="violet" className="size-9" />}
      >
        <p className="flex items-baseline gap-3">
          <span
            className="text-[2.5rem] leading-none font-bold tracking-[-0.02em] text-brand-navy tabular-nums"
            data-testid="quality-workspace-score"
          >
            {pct(score.score)} %
          </span>
          <LevelPill level={score.level} />
        </p>
        {/* No score 7 days ago yet: say nothing rather than « Stable ». */}
        {points === null ? null : (
          <p className="mt-2 flex items-center gap-1.5 text-[0.8125rem] text-shell-muted">
            {points > 0 ? (
            <TrendingUp className="size-4 text-state-success" aria-hidden="true" />
          ) : points < 0 ? (
            <TrendingDown className="size-4 text-state-danger" aria-hidden="true" />
          ) : null}
          <span data-testid="quality-change">
            {points === 0
              ? w.steady
              : fill(w.change, { sign: points > 0 ? "+" : "−", points: Math.abs(points) })}
          </span>
          </p>
        )}
        <p className="mt-1 text-xs text-shell-muted">
          {fill(w.measured, { when: timeAgo(t, score.measured_at) })}
        </p>
        <ul className="mt-3 flex flex-wrap gap-2" data-testid="quality-levels">
          {(["low", "medium", "high"] as const).map((level) => (
            <li key={level}>
              <Pill tone={LEVEL_TONES[level]}>
                {fill(w.counted, {
                  count: levels[level] ?? 0,
                  level: w.levels[level].toLowerCase(),
                })}
              </Pill>
            </li>
          ))}
        </ul>
      </Card>
      <Card title={w.title}>
        <Dimensions score={score} />
      </Card>
      <Card title={w.trend.title}>
        <QualityTrend points={trend} />
      </Card>
    </div>
  );
}

function AreaTable({ rows }: { rows: readonly QualityScore[] }) {
  const t = useDictionary();
  const w = t.knowledgeQuality.areas;
  const columns: KnowledgeColumn<QualityScore>[] = [
    {
      id: "name",
      header: w.name,
      sortValue: (row) => subjectName(t, row),
      cell: (row) => {
        const href = hrefOf(row);
        const name = subjectName(t, row);
        return href ? (
          <Link
            href={href}
            className="font-medium text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          >
            {name}
          </Link>
        ) : (
          <span className="font-medium text-brand-navy">{name}</span>
        );
      },
    },
    {
      id: "score",
      header: w.score,
      sortValue: (row) => row.score,
      cell: (row) => (
        <span className="flex items-center gap-3">
          <LevelPill level={row.level} />
          <span className="min-w-28 flex-1">
            <ScoreBar value={row.score} />
          </span>
        </span>
      ),
    },
    {
      id: "things",
      header: w.things,
      sortValue: (row) => row.entities,
      cell: (row) => row.entities,
    },
    {
      id: "lacks",
      header: w.lacks,
      cell: (row) => (
        <span className="text-[0.8125rem] text-shell-muted">
          {lacksSaid(t, row).join(" · ") || "—"}
        </span>
      ),
    },
  ];
  return (
    <KnowledgeTable
      caption={w.caption}
      columns={columns}
      rows={[...rows]}
      rowKey={(row) => row.key}
      empty={{ title: w.empty }}
      initialSort={{ id: "score", direction: "asc" }}
    />
  );
}

function Areas({ areas }: { areas: Record<Area, readonly QualityScore[]> }) {
  const t = useDictionary();
  const w = t.knowledgeQuality.areas;
  const [area, setArea] = useState<Area>("columns");
  return (
    <Card
      title={w.title}
      action={
        <div role="group" aria-label={w.title} className="flex gap-1">
          {AREAS.map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={area === key}
              onClick={() => setArea(key)}
              data-testid={`quality-area-${key}`}
              className={cn(
                "rounded-lg border px-2.5 py-1 text-xs font-medium outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
                area === key
                  ? "border-brand-violet/30 bg-brand-violet-soft text-shell-nav-active"
                  : "border-shell-line text-brand-navy hover:bg-shell-canvas",
              )}
            >
              {w[key]}
            </button>
          ))}
        </div>
      }
    >
      <AreaTable rows={areas[area]} />
    </Card>
  );
}

function Weakest() {
  const t = useDictionary();
  const w = t.knowledgeQuality.weakest;
  const [level, setLevel] = useState<QualityLevel | null>(null);
  const weakest = useWeakest(level);
  const columns: KnowledgeColumn<QualityScore>[] = [
    {
      id: "name",
      header: w.name,
      sortValue: (row) => row.subject.name,
      cell: (row) => {
        const href = hrefOf(row);
        return href ? (
          <Link
            href={href}
            className="font-medium text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          >
            {row.subject.name}
          </Link>
        ) : (
          <span className="font-medium text-brand-navy">{row.subject.name}</span>
        );
      },
    },
    {
      id: "score",
      header: w.score,
      sortValue: (row) => row.score,
      cell: (row) => (
        <span className="flex items-center gap-3">
          <LevelPill level={row.level} />
          <span className="min-w-28 flex-1">
            <ScoreBar value={row.score} />
          </span>
        </span>
      ),
    },
    {
      id: "lacks",
      header: w.lacks,
      cell: (row) => (
        <span className="text-[0.8125rem] text-shell-muted">
          {lacksSaid(t, row).join(" · ") || w.nothing}
        </span>
      ),
    },
  ];
  return (
    <Card
      title={w.title}
      action={
        <div role="group" aria-label={w.title} className="flex gap-1">
          {([null, "low", "medium", "high"] as const).map((key) => (
            <button
              key={key ?? "all"}
              type="button"
              aria-pressed={level === key}
              onClick={() => setLevel(key)}
              data-testid={`quality-filter-${key ?? "all"}`}
              className={cn(
                "rounded-lg border px-2.5 py-1 text-xs font-medium outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
                level === key
                  ? "border-brand-violet/30 bg-brand-violet-soft text-shell-nav-active"
                  : "border-shell-line text-brand-navy hover:bg-shell-canvas",
              )}
            >
              {key ? t.knowledgeQuality.levels[key] : w.all}
            </button>
          ))}
        </div>
      }
    >
      {weakest.isError ? (
        <ErrorState error={weakest.error} onRetry={() => void weakest.refetch()} />
      ) : (
        <KnowledgeTable
          caption={w.caption}
          columns={columns}
          rows={weakest.data?.data ?? []}
          rowKey={(row) => row.key}
          loading={weakest.isPending}
          empty={{ title: w.empty }}
          pageSize={10}
        />
      )}
    </Card>
  );
}

/** Mon environnement, tab Qualité. */
export function QualityTab() {
  const t = useDictionary();
  const w = t.knowledgeQuality;
  const summary = useQualitySummary();

  if (summary.isError) {
    return <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />;
  }
  const data = summary.data;
  if (!data) {
    return <div className="h-96 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  }
  if (!data.workspace) {
    return (
      <Card title={w.title} icon={<IconTile icon={Gauge} tone="violet" className="size-9" />}>
        <p className="text-[0.875rem] text-shell-muted" data-testid="quality-never">
          {w.never}
        </p>
      </Card>
    );
  }
  return (
    <div className="flex flex-col gap-4" data-testid="quality-tab">
      <p className="text-[0.875rem] text-shell-accent-muted">{w.subtitle}</p>
      <Headline
        score={data.workspace}
        change={data.change}
        levels={data.levels}
        trend={data.trend}
      />
      <Weakest />
      <Areas
        areas={{ columns: data.columns, teams: data.teams, applications: data.applications }}
      />
      <section className="rounded-xl bg-shell-highlight px-5 py-4" aria-labelledby="quality-method">
        <h2 id="quality-method" className="text-[0.9375rem] font-semibold text-brand-navy">
          {w.method.title}
        </h2>
        <p className="mt-1 text-[0.8125rem] text-shell-muted">{w.method.body}</p>
      </section>
    </div>
  );
}

// ── a thing's sheet ─────────────────────────────────────────────────────

function SheetBody({ score }: { score: QualityDetail }) {
  const t = useDictionary();
  const w = t.knowledgeQuality.sheet;
  const lacks = lacksSaid(t, score, 5);
  return (
    <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <div>
        <p className="flex items-baseline gap-3">
          <span
            className="text-[1.75rem] leading-none font-bold text-brand-navy tabular-nums"
            data-testid="quality-entity-score"
          >
            {pct(score.score)} %
          </span>
          <LevelPill level={score.level} />
        </p>
        <p className="mt-1 text-xs text-shell-muted">
          {fill(w.since, {
            level: t.knowledgeQuality.levels[score.level],
            when: timeAgo(t, score.since),
          })}
        </p>
        {score.capped ? (
          <p className="mt-1 text-xs text-shell-muted" data-testid="quality-capped">
            {(w.capped as Record<string, string>)[score.capped] ?? null}
          </p>
        ) : null}
        <div className="mt-3">
          <Dimensions score={score} />
        </div>
      </div>
      <div>
        <h3 className="mb-1.5 text-[0.8125rem] font-semibold text-brand-navy">{w.lacks}</h3>
        {lacks.length ? (
          <ul className="space-y-1 text-[0.8125rem] text-brand-navy" data-testid="quality-lacks">
            {lacks.map((lack) => (
              <li key={lack} className="flex items-start gap-2">
                <span aria-hidden="true" className="mt-1.5 size-1.5 rounded-full bg-shell-muted" />
                {lack}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[0.8125rem] text-state-success">{w.nothing}</p>
        )}
      </div>
    </div>
  );
}

/** A thing's sheet: its knowledge quality, or when it will be measured. */
export function EntityQuality({ id }: { id: string }) {
  const t = useDictionary();
  const w = t.knowledgeQuality.sheet;
  const quality = useEntityQuality(id);
  let body: React.ReactNode;
  if (quality.isError) {
    body = <ErrorState error={quality.error} onRetry={() => void quality.refetch()} />;
  } else if (quality.isPending) {
    body = <div className="h-24 animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />;
  } else if (!quality.data) {
    body = (
      <p className="text-[0.8125rem] text-shell-muted" data-testid="quality-entity-none">
        {w.none}
      </p>
    );
  } else {
    body = <SheetBody score={quality.data} />;
  }
  return (
    <Card title={w.title} icon={<IconTile icon={Gauge} tone="violet" className="size-9" />}>
      {body}
    </Card>
  );
}
