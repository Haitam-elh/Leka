"use client";

import {
  Activity,
  ArrowDown,
  ArrowUp,
  BadgeCheck,
  BookOpen,
  Bot,
  Briefcase,
  Cloud,
  Code,
  Database,
  FileText,
  Lightbulb,
  type LucideIcon,
  Network,
  Plus,
  Search,
  ShieldCheck,
  Star,
  TriangleAlert,
  Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { cn } from "cn";

import { IconTile, type TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { useConfirm } from "@/components/interactions/confirm";
import { PageContainer } from "@/components/shell/page-container";
import { hasSourceLogo, sourceTitle } from "@/components/sources/source-logo";
import { usePermissions } from "@/components/shell/shell-provider";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CAPABILITY_VIEWS, routes } from "@/config/routes";
import {
  type Capability,
  type CapabilityReason,
  type CatalogueQuery,
  type CatalogueSummary,
} from "@/lib/capabilities";
import {
  useCapabilities,
  useCapabilityChange,
  useCatalogueSummary,
} from "@/lib/capabilities-queries";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

/**
 * Capacités, as docs/product/mockups/13-capacites.jpeg (LEKA-393): what LEKA
 * can do — its own analyses and its agents — each said in words, with
 * whether it can be used here and, when not, why: a source to connect, the
 * language model to come, turned off. Every figure is real: what is
 * registered, what the workspace's analyses ran this week. Three views:
 * the available ones, « Mes capacités » — kept at hand — and, for admins,
 * their configuration.
 */

type View = (typeof CAPABILITY_VIEWS)[number];

export const CATEGORY_ICON: Record<string, LucideIcon> = {
  architecture: Network,
  development: Code,
  infrastructure: Cloud,
  operations: Activity,
  security: ShieldCheck,
  compliance: BadgeCheck,
  data: Database,
  documentation: FileText,
  project_management: Users,
  business: Briefcase,
  knowledge: BookOpen,
};
export const CATEGORY_TONE: Record<string, TileTone> = {
  architecture: "violet",
  development: "info",
  infrastructure: "info",
  operations: "warning",
  security: "success",
  compliance: "success",
  data: "violet",
  documentation: "warning",
  project_management: "danger",
  business: "neutral",
  knowledge: "neutral",
};
const CATEGORY_FILL: Record<string, string> = {
  architecture: "fill-shell-nav-active",
  development: "fill-chart-1",
  infrastructure: "fill-state-info",
  operations: "fill-activity-alert",
  security: "fill-state-success",
  compliance: "fill-chart-2",
  data: "fill-chart-3",
  documentation: "fill-state-warning",
  project_management: "fill-chart-4",
  business: "fill-brand-navy",
  knowledge: "fill-chart-5",
};
const CATEGORY_DOT: Record<string, string> = {
  architecture: "bg-shell-nav-active",
  development: "bg-chart-1",
  infrastructure: "bg-state-info",
  operations: "bg-activity-alert",
  security: "bg-state-success",
  compliance: "bg-chart-2",
  data: "bg-chart-3",
  documentation: "bg-state-warning",
  project_management: "bg-chart-4",
  business: "bg-brand-navy",
  knowledge: "bg-chart-5",
};

function categorySaid(t: Dictionary, category: string): string {
  return (t.catalogue.categories as Record<string, string>)[category] ?? category;
}

/** Its title: LEKA's own in its words, an agent's as its file says it. */
export function titleOf(
  t: Dictionary,
  c: Pick<Capability, "key" | "title"> & { kind?: Capability["kind"] },
): string {
  if (c.kind === "agent") return c.title;
  return (t.intentions.analysis.capabilities as Record<string, string>)[c.key] ?? c.title;
}

/** What it does, in the reader's words: LEKA's own capabilities' and its
 * agents' from the dictionary — an agent's file describes it for the model
 * that chooses it — any other agent's as its file says it. */
export function summaryOf(t: Dictionary, c: Pick<Capability, "key" | "summary">): string {
  return (t.catalogue.summaries as Record<string, string>)[c.key] ?? c.summary;
}

/** Why it cannot be used here, in words. */
export function reasonSaid(t: Dictionary, reason: CapabilityReason): string {
  const w = t.catalogue.reasons as Record<string, string>;
  if (reason.code === "missing_source") {
    const said = reason.detail?.any_of;
    const kinds = Array.isArray(said) ? said.map(String) : [];
    const names = kinds.map((k) => (hasSourceLogo(k) ? sourceTitle(k) : k));
    return fill(w.missing_source, { sources: names.join(t.catalogue.or) });
  }
  return w[reason.code] ?? w.unknown;
}

function useView(): [View, (next: View) => void] {
  const router = useRouter();
  const pathname = usePathname() ?? routes.capabilities();
  const search = useSearchParams();
  const asked = search?.get("tab");
  const view: View = (CAPABILITY_VIEWS as readonly string[]).includes(asked ?? "")
    ? (asked as View)
    : "available";
  function setView(next: View) {
    router.replace(next === "available" ? pathname : `${pathname}?tab=${next}`, {
      scroll: false,
    });
  }
  return [view, setView];
}

function Trend({ now, before, goodWhenDown = false }: { now: number; before: number; goodWhenDown?: boolean }) {
  const t = useDictionary();
  if (!before) return <span className="text-xs text-shell-muted">{t.catalogue.versus}</span>;
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

/** Why one cannot run that is the place's, not the capability's. */
const WIDE = ["no_model", "no_runtime"] as const;
type Wide = (typeof WIDE)[number];

function isWide(reason: CapabilityReason): boolean {
  return (WIDE as readonly string[]).includes(reason.code);
}

function Availability({ capability }: { capability: Capability }) {
  const t = useDictionary();
  if (capability.available) {
    return capability.notes.length ? (
      <Pill tone="warning">{reasonSaid(t, capability.notes[0])}</Pill>
    ) : (
      <Pill tone="success" dot>
        {t.catalogue.available}
      </Pill>
    );
  }
  // What holds every capability back is said once, above the list.
  const own = capability.reasons.filter((reason) => !isWide(reason));
  if (!own.length) {
    return (
      <Pill tone="neutral">
        {t.catalogue.unavailable}
        <span className="sr-only">
          {" : "}
          {capability.reasons.map((reason) => reasonSaid(t, reason)).join(" · ")}
        </span>
      </Pill>
    );
  }
  return (
    <span className="text-xs text-state-warning" data-testid="capability-reasons">
      {own.map((reason) => reasonSaid(t, reason)).join(" · ")}
    </span>
  );
}

function Favourite({ capability }: { capability: Capability }) {
  const t = useDictionary();
  const { favourite } = useCapabilityChange();
  const label = capability.favourite ? t.catalogue.unfavourite : t.catalogue.favourite;
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={capability.favourite}
      title={label}
      disabled={favourite.isPending}
      onClick={() => favourite.mutate({ key: capability.key, on: !capability.favourite })}
      className="rounded p-1 text-shell-muted hover:bg-shell-canvas hover:text-shell-nav-active"
      data-testid="capability-favourite"
    >
      <Star
        className={cn("size-4", capability.favourite && "fill-state-warning text-state-warning")}
        aria-hidden="true"
      />
    </button>
  );
}

/** One of them, a line of its domain: what it is, what it does, whether it
 * can be used here. Its sheet one click away. */
function Row({ capability }: { capability: Capability }) {
  const t = useDictionary();
  const agent = capability.kind === "agent";
  const Icon = agent ? Bot : (CATEGORY_ICON[capability.category] ?? Lightbulb);
  // Available and nothing to say: the line says nothing about it.
  const plain = capability.available && !capability.notes.length;
  return (
    <li
      className="flex items-start gap-3 py-2.5"
      data-testid="capability-card"
      data-key={capability.key}
      data-kind={capability.kind}
      data-available={capability.available ? "true" : "false"}
    >
      <IconTile
        icon={Icon}
        tone={agent ? "violet" : (CATEGORY_TONE[capability.category] ?? "neutral")}
        className="size-9"
      />
      <div className="min-w-0 flex-1">
        <Link
          href={routes.capability(capability.key)}
          className="line-clamp-1 text-[0.9375rem] leading-snug font-semibold text-brand-navy hover:underline"
          title={titleOf(t, capability)}
        >
          {titleOf(t, capability)}
        </Link>
        <p className="line-clamp-2 text-[0.8125rem] leading-snug text-shell-muted">
          {summaryOf(t, capability)}
        </p>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
          {capability.usage.runs ? (
            <span className="text-xs text-shell-muted">
              {fill(t.catalogue.runs, { count: capability.usage.runs })}
            </span>
          ) : null}
          {plain ? (
            <span className="sr-only">{t.catalogue.available}</span>
          ) : (
            <Availability capability={capability} />
          )}
        </div>
      </div>
      <Favourite capability={capability} />
    </li>
  );
}

/** The domains, in the order a team reads its work: code first. */
const DOMAINS = [
  "development",
  "architecture",
  "operations",
  "security",
  "compliance",
  "infrastructure",
  "data",
  "documentation",
  "knowledge",
  "project_management",
  "business",
] as const;

type Shown = "all" | "agents" | "capabilities";

/** One box per domain (2026-10-14: « une case avec les agents et capacités
 * sur le code, pareil pour les autres ») — its agents first, then LEKA's own
 * capabilities, never mixed. */
function Domain({ category, items }: { category: string; items: Capability[] }) {
  const t = useDictionary();
  const w = t.catalogue;
  const agents = items.filter((c) => c.kind === "agent");
  const own = items.filter((c) => c.kind !== "agent");
  const Icon = CATEGORY_ICON[category] ?? Lightbulb;
  return (
    <section
      className="flex flex-col overflow-hidden rounded-xl border border-shell-line bg-white"
      aria-labelledby={`domain-${category}`}
      data-testid="catalogue-domain"
      data-domain={category}
    >
      <header className="flex items-center gap-2.5 border-b border-shell-line bg-shell-canvas/60 px-4 py-3">
        <IconTile icon={Icon} tone={CATEGORY_TONE[category] ?? "neutral"} className="size-8" />
        <h2 id={`domain-${category}`} className="min-w-0 flex-1 text-[1rem] font-semibold text-brand-navy">
          {(w.domains as Record<string, string>)[category] ?? categorySaid(t, category)}
        </h2>
        <span className="text-xs text-shell-muted" data-testid="catalogue-domain-count">
          {[
            agents.length ? fill(w.agentsCount, { count: agents.length }) : null,
            own.length ? fill(w.ownCount, { count: own.length }) : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </header>
      {agents.length ? (
        <div className="px-4 pt-3" data-testid="catalogue-domain-agents">
          <p className="text-xs font-semibold tracking-wide text-shell-nav-active uppercase">{w.agentsTitle}</p>
          <ul className="divide-y divide-shell-line/70">
            {agents.map((capability) => (
              <Row key={capability.key} capability={capability} />
            ))}
          </ul>
        </div>
      ) : null}
      {own.length ? (
        <div
          className={cn("px-4 pb-1", agents.length ? "border-t border-shell-line pt-3" : "pt-3")}
          data-testid="catalogue-domain-own"
        >
          <p className="text-xs font-semibold tracking-wide text-shell-nav uppercase">{w.ownTitle}</p>
          <ul className="divide-y divide-shell-line/70">
            {own.map((capability) => (
              <Row key={capability.key} capability={capability} />
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

const WIDTH = 320;
const HEIGHT = 140;
const BOTTOM = 18;

function UsageChart({ summary }: { summary: CatalogueSummary }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const used = summary.categories.map((c) => c.category);
  const totals = summary.days.map((d) => Object.values(d.runs).reduce((a, b) => a + b, 0));
  const top = Math.max(4, ...totals);
  const slot = WIDTH / Math.max(1, summary.days.length);
  const bar = slot * 0.5;
  const plot = HEIGHT - BOTTOM;
  const day = new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
  });
  return (
    <section className="rounded-xl border border-shell-line bg-white p-4" data-testid="catalogue-usage">
      <h2 className="mb-2 font-semibold text-brand-navy">{t.catalogue.usage}</h2>
      {summary.runs === 0 ? (
        <p className="text-[0.8125rem] text-shell-muted">{t.catalogue.usageEmpty}</p>
      ) : (
        <>
          <ul className="mb-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-shell-muted">
            {used
              .filter((c) => summary.days.some((d) => d.runs[c]))
              .map((c) => (
                <li key={c} className="flex items-center gap-1">
                  <span className={cn("size-2 rounded-full", CATEGORY_DOT[c] ?? "bg-shell-muted")} />
                  {categorySaid(t, c)}
                </li>
              ))}
          </ul>
          <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-auto w-full" role="img" aria-label={t.catalogue.usage}>
            {summary.days.map((d, index) => {
              let y = plot;
              return (
                <g key={d.day}>
                  {used.map((category) => {
                    const runs = d.runs[category] ?? 0;
                    if (!runs) return null;
                    const height = (runs / top) * (plot - 4);
                    y -= height;
                    return (
                      <rect
                        key={category}
                        x={index * slot + (slot - bar) / 2}
                        y={y}
                        width={bar}
                        height={height}
                        rx={2}
                        className={CATEGORY_FILL[category] ?? "fill-shell-muted"}
                      />
                    );
                  })}
                  <text
                    x={index * slot + slot / 2}
                    y={HEIGHT - 4}
                    textAnchor="middle"
                    className="fill-shell-muted text-[9px]"
                  >
                    {day.format(new Date(`${d.day}T12:00:00Z`))}
                  </text>
                </g>
              );
            })}
          </svg>
        </>
      )}
    </section>
  );
}

function Top({ summary }: { summary: CatalogueSummary }) {
  const t = useDictionary();
  return (
    <section className="rounded-xl border border-shell-line bg-white p-4" data-testid="catalogue-top">
      <h2 className="mb-2 font-semibold text-brand-navy">{t.catalogue.top}</h2>
      {summary.top.length ? (
        <ol className="space-y-2">
          {summary.top.map((item, index) => {
            const Icon = CATEGORY_ICON[item.category] ?? Lightbulb;
            return (
              <li key={item.key} className="flex items-center gap-2 text-[0.8125rem]">
                <span className="flex size-5 items-center justify-center rounded-full bg-shell-canvas text-[0.6875rem] text-shell-muted">
                  {index + 1}
                </span>
                <Icon className="size-4 text-shell-nav-active" aria-hidden="true" />
                <Link href={routes.capability(item.key)} className="min-w-0 flex-1 truncate text-brand-navy hover:underline">
                  {titleOf(t, { key: item.key, kind: "rules", title: item.title })}
                </Link>
                <span className="text-shell-muted tabular-nums">{item.runs}</span>
                <Trend now={item.runs} before={item.previous} />
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="text-[0.8125rem] text-shell-muted">{t.catalogue.topEmpty}</p>
      )}
    </section>
  );
}

function Latest({ summary }: { summary: CatalogueSummary }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  return (
    <section className="rounded-xl border border-shell-line bg-white p-4" data-testid="catalogue-latest">
      <h2 className="mb-2 font-semibold text-brand-navy">{t.catalogue.latest}</h2>
      {summary.latest.length ? (
        <ul className="space-y-3">
          {summary.latest.map((item) => {
            const Icon = CATEGORY_ICON[item.category] ?? Lightbulb;
            return (
              <li key={item.key} className="flex items-start gap-2 text-[0.8125rem]">
                <Icon className="mt-0.5 size-4 text-shell-nav-active" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <Link href={routes.capability(item.key)} className="font-medium text-brand-navy hover:underline">
                    {titleOf(t, item)}
                  </Link>
                  <p className="line-clamp-1 text-xs text-shell-muted">{summaryOf(t, item)}</p>
                </div>
                <time dateTime={item.registered_at} className="shrink-0 text-xs text-shell-muted">
                  {new Intl.DateTimeFormat(locale, {
                    day: "numeric",
                    month: "short",
                    year: "numeric",
                  }).format(new Date(item.registered_at))}
                </time>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-[0.8125rem] text-shell-muted">{t.catalogue.latestEmpty}</p>
      )}
    </section>
  );
}

function Domains({
  list,
  goal,
  shown,
  empty,
}: {
  list: ReturnType<typeof useCapabilities>;
  goal: string | null;
  shown: Shown;
  empty: string;
}) {
  const t = useDictionary();
  if (list.isError) {
    return (
      <p className="rounded-xl border border-shell-line bg-white p-4 text-sm text-shell-muted" role="alert">
        {t.catalogue.failed}{" "}
        <button type="button" className="font-medium text-shell-nav-active hover:underline" onClick={() => void list.refetch()}>
          {t.catalogue.retry}
        </button>
      </p>
    );
  }
  if (!list.data) return <div className="h-80 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  const kept = list.data.filter(
    (capability) =>
      (!goal || capability.goals.includes(goal)) &&
      (shown === "all" || (shown === "agents") === (capability.kind === "agent")),
  );
  if (!kept.length) {
    return (
      <p className="rounded-xl border border-shell-line bg-white px-5 py-6 text-[0.875rem] text-shell-muted" data-testid="catalogue-empty">
        {empty}
      </p>
    );
  }
  const known = DOMAINS as readonly string[];
  const order = [
    ...known,
    ...[...new Set(kept.map((c) => c.category))].filter((c) => !known.includes(c)).sort(),
  ];
  return (
    <div className="grid items-start gap-4 xl:grid-cols-2" data-testid="catalogue-grid">
      {order.map((category) => {
        const items = kept.filter((c) => c.category === category);
        return items.length ? <Domain key={category} category={category} items={items} /> : null;
      })}
    </div>
  );
}

/** What keeps several from running here, said once (LEKA-438). */
function WideReasons({ capabilities }: { capabilities: Capability[] }) {
  const t = useDictionary();
  const admin = usePermissions()?.includes("workspace:update") ?? false;
  const held = WIDE.map((code) => ({
    code,
    count: capabilities.filter((c) => c.reasons.some((reason) => reason.code === code)).length,
  })).filter((wide) => wide.count);
  if (!held.length) return null;
  return (
    <ul className="flex flex-col gap-2" data-testid="catalogue-wide">
      {held.map(({ code, count }: { code: Wide; count: number }) => (
        <li
          key={code}
          className="flex flex-wrap items-center gap-3 rounded-xl border border-state-warning/40 bg-state-warning/5 px-4 py-3 text-[0.875rem] text-brand-navy"
        >
          <TriangleAlert className="size-4 shrink-0 text-state-warning" aria-hidden="true" />
          <span className="min-w-0 flex-1">{fill(t.catalogue.wide[code], { count })}</span>
          {code === "no_model" && admin ? (
            <Link href={routes.settings()} className={buttonVariants({ variant: "outline", size: "sm" })}>
              {t.catalogue.wide.configure}
            </Link>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

const GOALS = [
  "explain_cause",
  "investigate",
  "find_change",
  "assess_impact",
  "map_dependencies",
  "find_owner",
  "check_compliance",
  "plan_migration",
  "find_knowledge",
  "act",
] as const;

function Filters({
  capabilities,
  goal,
  setGoal,
  shown,
  setShown,
  q,
  setQ,
  sort,
  setSort,
}: {
  capabilities: Capability[] | undefined;
  goal: string | null;
  setGoal: (next: string | null) => void;
  shown: Shown;
  setShown: (next: Shown) => void;
  q: string;
  setQ: (next: string) => void;
  sort: NonNullable<CatalogueQuery["sort"]>;
  setSort: (next: NonNullable<CatalogueQuery["sort"]>) => void;
}) {
  const t = useDictionary();
  const w = t.catalogue;
  const needs = GOALS.map((need) => ({
    need,
    count: (capabilities ?? []).filter((c) => c.goals.includes(need)).length,
  })).filter((n) => n.count);
  const chip = (active: boolean) =>
    cn(
      "flex h-8 shrink-0 items-center gap-1.5 rounded-lg border px-2.5 text-[0.75rem] font-medium whitespace-nowrap",
      active
        ? "border-shell-nav-active bg-brand-violet-soft text-shell-nav-active"
        : "border-shell-line bg-white text-brand-navy hover:bg-shell-canvas",
    );
  return (
    <div className="flex flex-col gap-3" data-testid="catalogue-filters">
      <div className="flex flex-col gap-2 md:flex-row md:items-center">
        <label className="relative flex min-w-0 flex-1 items-center">
          <Search className="absolute start-2.5 size-4 text-shell-muted" aria-hidden="true" />
          <input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder={w.search}
            aria-label={w.search}
            className="h-9 w-full rounded-lg border border-shell-line bg-white pe-2 ps-8 text-sm text-brand-navy outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40"
            data-testid="catalogue-search"
          />
        </label>
        <div className="flex items-center gap-2">
          {/* Agents, or LEKA's own capabilities, or both: the domains are the
              boxes below (2026-10-14). */}
          <div role="group" aria-label={w.show} className="flex rounded-lg border border-shell-line bg-white p-0.5">
            {(["all", "agents", "capabilities"] as const).map((each) => (
              <button
                key={each}
                type="button"
                aria-pressed={shown === each}
                onClick={() => setShown(each)}
                data-testid={`catalogue-show-${each}`}
                className={cn(
                  "h-8 rounded-md px-2.5 text-[0.8125rem] font-medium whitespace-nowrap",
                  shown === each ? "bg-brand-violet-soft text-shell-nav-active" : "text-shell-nav hover:bg-shell-canvas",
                )}
              >
                {w.shows[each]}
              </button>
            ))}
          </div>
          <Select
            value={sort}
            onValueChange={(next) => setSort((next ?? sort) as NonNullable<CatalogueQuery["sort"]>)}
            items={(["relevant", "name", "recent"] as const).map((value) => ({ value, label: w.sorts[value] }))}
          >
            <SelectTrigger className="min-w-40 bg-white" aria-label={w.sort}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(["relevant", "name", "recent"] as const).map((value) => (
                <SelectItem key={value} value={value}>
                  {w.sorts[value]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      {needs.length ? (
        <div role="group" aria-labelledby="catalogue-need" className="flex flex-wrap items-center gap-1.5">
          <span id="catalogue-need" className="me-1 text-[0.8125rem] font-medium text-brand-navy">
            {w.need}
          </span>
          <button type="button" className={chip(goal === null)} onClick={() => setGoal(null)} aria-pressed={goal === null}>
            {w.allNeeds}
          </button>
          {needs.map(({ need, count }) => (
            <button
              key={need}
              type="button"
              className={chip(goal === need)}
              onClick={() => setGoal(goal === need ? null : need)}
              aria-pressed={goal === need}
              data-testid={`catalogue-need-${need}`}
            >
              {t.intentions.understanding.goals[need]}
              <span className="rounded bg-white/70 px-1 text-xs text-shell-muted">{count}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Configuration() {
  const t = useDictionary();
  const w = t.catalogue.configuration;
  const admin = usePermissions()?.includes("workspace:update") ?? false;
  const list = useCapabilities({ everything: true, sort: "name" });
  const { settings } = useCapabilityChange();
  const confirm = useConfirm();

  async function toggle(capability: Capability) {
    if (capability.enabled) {
      const reason = await confirm({
        title: w.disableTitle,
        description: w.disableBody,
        confirmLabel: w.disable,
        destructive: true,
        reasonLabel: w.reason,
      });
      if (reason === null) return;
      if (!reason.trim()) {
        notify.error({ title: w.reasonRequired });
        return;
      }
      await settings.mutateAsync({ key: capability.key, enabled: false, reason: reason.trim() });
    } else {
      await settings.mutateAsync({ key: capability.key, enabled: true });
    }
    notify.success({ title: w.done });
  }

  return (
    <section className="rounded-xl border border-shell-line bg-white p-4" data-testid="catalogue-configuration">
      <h2 className="font-semibold text-brand-navy">{w.title}</h2>
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{admin ? w.body : w.readOnly}</p>
      {!list.data ? (
        <div className="h-64 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />
      ) : (
        <ul className="divide-y divide-shell-line">
          {list.data.map((capability) => (
            <li
              key={capability.key}
              className="flex flex-wrap items-center gap-3 py-2.5"
              data-testid="configuration-row"
              data-key={capability.key}
            >
              <div className="min-w-0 flex-1">
                <Link href={routes.capability(capability.key)} className="text-[0.875rem] font-medium text-brand-navy hover:underline">
                  {titleOf(t, capability)}
                </Link>
                <p className="text-xs text-shell-muted">
                  {categorySaid(t, capability.category)} · {t.catalogue.kinds[capability.kind]} · v
                  {capability.version} · {t.catalogue.lifecycles[capability.lifecycle]}
                  {!capability.enabled && capability.enabled_reason
                    ? ` · ${fill(w.disabledBecause, { reason: capability.enabled_reason })}`
                    : ""}
                </p>
              </div>
              <Pill tone={capability.enabled ? "success" : "neutral"}>
                {capability.enabled ? t.catalogue.lifecycles.active : t.catalogue.reasons.disabled}
              </Pill>
              {admin ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={settings.isPending}
                  onClick={() => void toggle(capability)}
                  data-testid="configuration-toggle"
                >
                  {capability.enabled ? w.disable : w.enable}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function CatalogueScreen() {
  const t = useDictionary();
  const w = t.catalogue;
  const [view, setView] = useView();
  const summary = useCatalogueSummary();
  const [shown, setShown] = useState<Shown>("all");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<NonNullable<CatalogueQuery["sort"]>>("relevant");
  const [goal, setGoal] = useState<string | null>(null);
  const list = useCapabilities({ view: view === "mine" ? "mine" : "all", q, sort });
  const empty = view === "mine" && shown === "all" && !q && !goal ? w.mineEmpty : w.empty;

  return (
    <PageContainer>
      <div className="mb-5 flex flex-col gap-4 md:flex-row md:items-start">
        <div className="min-w-0 flex-1">
          <h1 className="text-[2.125rem] leading-tight font-bold tracking-[-0.02em] text-brand-navy">{w.title}</h1>
          <p className="mt-1 text-[1.0625rem] text-shell-accent-muted">{w.subtitle}</p>
        </div>
        <Link href={routes.intentionNew()} className={buttonVariants({ variant: "default" })} data-testid="catalogue-ask">
          <Plus className="size-4" aria-hidden="true" />
          {w.ask}
        </Link>
      </div>

      <div className="mb-4 flex gap-1 border-b border-shell-line" role="tablist" aria-label={w.title}>
        {CAPABILITY_VIEWS.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={view === name}
            onClick={() => setView(name)}
            data-testid={`catalogue-view-${name}`}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-[0.875rem] font-medium",
              view === name
                ? "border-shell-nav-active text-shell-nav-active"
                : "border-transparent text-shell-muted hover:text-brand-navy",
            )}
          >
            {w.views[name]}
          </button>
        ))}
      </div>

      {view === "configuration" ? (
        <Configuration />
      ) : (
        <div className="flex flex-col gap-4">
          {list.data ? <WideReasons capabilities={list.data} /> : null}
          <Filters
            capabilities={list.data}
            goal={goal}
            setGoal={setGoal}
            shown={shown}
            setShown={setShown}
            q={q}
            setQ={setQ}
            sort={sort}
            setSort={setSort}
          />
          <Domains list={list} goal={goal} shown={shown} empty={empty} />
          {/* What ran this week, under what there is — nothing ran, nothing
              said. */}
          {summary.data?.runs ? (
            <div className="grid gap-4 lg:grid-cols-3" data-testid="catalogue-usage">
              <UsageChart summary={summary.data} />
              <Top summary={summary.data} />
              <Latest summary={summary.data} />
            </div>
          ) : null}
        </div>
      )}
    </PageContainer>
  );
}
