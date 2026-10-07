"use client";

import { cn } from "cn";

import { type ActivityBucket, type ActivityCategory, CATEGORIES } from "@/lib/activity";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";

/**
 * Activité's two drawings (LEKA-383), as mockup 08 draws them — by hand, in
 * SVG: the events of each day (or week) stacked by type, and the period's
 * split. One scale places the bars, the ticks and their labels; every
 * label names a value the chart reaches.
 */

export const CATEGORY_FILL: Record<ActivityCategory, string> = {
  information: "fill-activity-information",
  action: "fill-activity-action",
  alert: "fill-activity-alert",
  incident: "fill-activity-incident",
};

export const CATEGORY_DOT: Record<ActivityCategory, string> = {
  information: "bg-activity-information",
  action: "bg-activity-action",
  alert: "bg-activity-alert",
  incident: "bg-activity-incident",
};

export const CATEGORY_STROKE: Record<ActivityCategory, string> = {
  information: "stroke-activity-information",
  action: "stroke-activity-action",
  alert: "stroke-activity-alert",
  incident: "stroke-activity-incident",
};

export interface Column {
  /** The first day it holds. */
  day: string;
  counts: Record<ActivityCategory, number>;
}

function total(column: Column): number {
  return CATEGORIES.reduce((sum, category) => sum + column.counts[category], 0);
}

/** The days as they come — or, by week, seven at a time from the first. */
export function columns(buckets: readonly ActivityBucket[], byWeek: boolean): Column[] {
  const size = byWeek ? 7 : 1;
  const found: Column[] = [];
  for (let start = 0; start < buckets.length; start += size) {
    const slice = buckets.slice(start, start + size);
    found.push({
      day: slice[0].day,
      counts: Object.fromEntries(
        CATEGORIES.map((category) => [category, slice.reduce((sum, b) => sum + b[category], 0)]),
      ) as Record<ActivityCategory, number>,
    });
  }
  return found;
}

/** A top the axis reaches, round: 1, 2, 5 × 10ⁿ, in four steps. */
export function niceTop(max: number): number {
  if (max <= 4) return 4;
  const step = max / 4;
  const power = 10 ** Math.floor(Math.log10(step));
  const nice = [1, 2, 2.5, 5, 10].find((m) => m * power >= step) ?? 10;
  return nice * power * 4;
}

const WIDTH = 640;
const HEIGHT = 200;
const LEFT = 32;
const BOTTOM = 24;
const TOP = 8;

export function StackedBars({ data, className }: { data: readonly Column[]; className?: string }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const top = niceTop(Math.max(0, ...data.map(total)));
  const plot = HEIGHT - BOTTOM - TOP;
  const slot = (WIDTH - LEFT) / Math.max(1, data.length);
  const bar = Math.min(36, slot * 0.55);
  const y = (value: number) => TOP + plot - (value / top) * plot;
  const every = Math.ceil(data.length / 8);
  const label = new Intl.DateTimeFormat(locale === "fr" ? "fr-FR" : "en-GB", {
    day: "numeric",
    month: "short",
  });

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className={cn("h-auto w-full", className)}
      role="img"
      aria-label={t.activity.chart.caption}
      data-testid="activity-bars"
    >
      {[0, 1, 2, 3, 4].map((step) => {
        const value = (top / 4) * step;
        return (
          <g key={step}>
            <line
              x1={LEFT}
              x2={WIDTH}
              y1={y(value)}
              y2={y(value)}
              className="stroke-shell-line"
              strokeDasharray={step ? "3 4" : undefined}
            />
            <text
              x={LEFT - 8}
              y={y(value) + 4}
              textAnchor="end"
              className="fill-shell-muted text-[11px]"
            >
              {Number.isInteger(value) ? value : value.toFixed(1)}
            </text>
          </g>
        );
      })}
      {data.map((column, index) => {
        const x = LEFT + slot * index + (slot - bar) / 2;
        let base = 0;
        return (
          <g key={column.day} data-testid="activity-bar">
            <title>
              {[
                label.format(new Date(`${column.day}T12:00:00`)),
                ...CATEGORIES.filter((c) => column.counts[c]).map(
                  (c) => `${t.activity.categories[c]} : ${column.counts[c]}`,
                ),
              ].join("\n")}
            </title>
            {CATEGORIES.map((category) => {
              const value = column.counts[category];
              if (!value) return null;
              const from = base;
              base += value;
              return (
                <rect
                  key={category}
                  x={x}
                  y={y(base)}
                  width={bar}
                  height={Math.max(1, y(from) - y(base))}
                  className={CATEGORY_FILL[category]}
                />
              );
            })}
            {index % every === 0 ? (
              <text
                x={x + bar / 2}
                y={HEIGHT - 6}
                textAnchor="middle"
                className="fill-shell-muted text-[11px]"
              >
                {label.format(new Date(`${column.day}T12:00:00`))}
              </text>
            ) : null}
          </g>
        );
      })}
    </svg>
  );
}

const RADIUS = 42;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export function Donut({
  counts,
  className,
}: {
  counts: Record<ActivityCategory, number>;
  className?: string;
}) {
  const t = useDictionary();
  const sum = CATEGORIES.reduce((s, c) => s + counts[c], 0);
  let offset = 0;
  return (
    <svg
      viewBox="0 0 120 120"
      className={cn("size-36 shrink-0", className)}
      role="img"
      aria-label={`${sum} ${t.activity.split.total}`}
    >
      <circle cx="60" cy="60" r={RADIUS} fill="none" strokeWidth="14" className="stroke-shell-canvas" />
      {sum
        ? CATEGORIES.map((category) => {
            const length = (counts[category] / sum) * CIRCUMFERENCE;
            const start = offset;
            offset += length;
            return length ? (
              <circle
                key={category}
                cx="60"
                cy="60"
                r={RADIUS}
                fill="none"
                strokeWidth="14"
                strokeDasharray={`${length} ${CIRCUMFERENCE - length}`}
                strokeDashoffset={-start}
                transform="rotate(-90 60 60)"
                className={CATEGORY_STROKE[category]}
              />
            ) : null;
          })
        : null}
      <text x="60" y="60" textAnchor="middle" className="fill-brand-navy text-[20px] font-bold">
        {sum}
      </text>
      <text x="60" y="76" textAnchor="middle" className="fill-shell-muted text-[9px]">
        {t.activity.split.total}
      </text>
    </svg>
  );
}
