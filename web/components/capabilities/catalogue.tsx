"use client";

import {
  Activity,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  BadgeCheck,
  BookOpen,
  Bot,
  Briefcase,
  Cloud,
  Code,
  Database,
  FileText,
  Gauge,
  Layers,
  Lightbulb,
  type LucideIcon,
  Network,
  Play,
  Plus,
  Search,
  ShieldCheck,
  Star,
  Timer,
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
export function titleOf(t: Dictionary, c: Pick<Capability, "key" | "kind" | "title">): string {
  if (c.kind === "agent") return c.title;
  return (t.intentions.analysis.capabilities as Record<string, string>)[c.key] ?? c.title;
}

export function summaryOf(t: Dictionary, c: Pick<Capability, "key" | "kind" | "summary">): string {
  if (c.kind === "agent") return c.summary;
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
  if (!before) return <span className="text-xs text-shell-muted">{t.catalogue.stats.versus}</span>;
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

function minutes(ms: number | null | undefined, locale: string): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 60_000) {
    return `${new Intl.NumberFormat(locale === "fr" ? "fr-FR" : "en-GB", { maximumFractionDigits: 1 }).format(ms / 1000)} s`;
  }
  return `${new Intl.NumberFormat(locale === "fr" ? "fr-FR" : "en-GB", { maximumFractionDigits: 1 }).format(ms / 60_000)} min`;
}

function Stats({ summary }: { summary: CatalogueSummary }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const s = t.catalogue.stats;
  const tiles: { key: string; icon: LucideIcon; tone: TileTone; value: string; label: string; foot: React.ReactNode }[] = [
    {
      key: "available",
      icon: Layers,
      tone: "violet",
      value: String(summary.available),
      label: s.available,
      foot: (
        <span className="text-xs text-shell-muted">
          {fill(s.availableFoot, { total: summary.total, added: summary.added_this_month })}
        </span>
      ),
    },
    {
      key: "categories",
      icon: Users,
      tone: "violet",
      value: String(summary.categories.length),
      label: s.categories,
      foot: <span className="text-xs text-shell-muted">{s.categoriesFoot}</span>,
    },
    {
      key: "runs",
      icon: Play,
      tone: "success",
      value: new Intl.NumberFormat(locale === "fr" ? "fr-FR" : "en-GB").format(summary.runs),
      label: s.runs,
      foot: summary.runs || summary.runs_previous ? (
        <Trend now={summary.runs} before={summary.runs_previous} />
      ) : (
        <span className="text-xs text-shell-muted">{s.noRuns}</span>
      ),
    },
    {
      key: "analysis",
      icon: Timer,
      tone: "warning",
      value: minutes(summary.analysis_ms, locale),
      label: s.analysis,
      foot:
        summary.analysis_ms && summary.analysis_previous_ms ? (
          <Trend now={summary.analysis_ms} before={summary.analysis_previous_ms} goodWhenDown />
        ) : (
          <span className="text-xs text-shell-muted">{s.versus}</span>
        ),
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4" data-testid="catalogue-stats">
      {tiles.map((tile) => (
        <div
          key={tile.key}
          className="flex items-start gap-3 rounded-xl border border-shell-line bg-white p-4"
          data-testid={`catalogue-stat-${tile.key}`}
        >
          <IconTile icon={tile.icon} tone={tile.tone} />
          <div className="min-w-0">
            <p className="text-[1.5rem] leading-tight font-bold text-brand-navy tabular-nums">
              {tile.value}
            </p>
            <p className="text-[0.8125rem] text-shell-muted">{tile.label}</p>
            <div className="mt-0.5">{tile.foot}</div>
          </div>
        </div>
      ))}
    </div>
  );
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
  return (
    <span className="text-xs text-state-warning" data-testid="capability-reasons">
      {capability.reasons.map((reason) => reasonSaid(t, reason)).join(" · ")}
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

function Card({ capability }: { capability: Capability }) {
  const t = useDictionary();
  const Icon = capability.kind === "agent" ? Bot : (CATEGORY_ICON[capability.category] ?? Lightbulb);
  return (
    <li
      className="flex flex-col gap-3 rounded-xl border border-shell-line bg-white p-4"
      data-testid="capability-card"
      data-key={capability.key}
      data-available={capability.available ? "true" : "false"}
    >
      <div className="flex items-start gap-3">
        <IconTile icon={Icon} tone={CATEGORY_TONE[capability.category] ?? "neutral"} />
        <div className="min-w-0 flex-1">
          <Link
            href={routes.capability(capability.key)}
            className="font-semibold text-brand-navy hover:underline"
          >
            {titleOf(t, capability)}
          </Link>
          <p className="mt-0.5 line-clamp-3 text-[0.8125rem] text-shell-muted">
            {summaryOf(t, capability)}
          </p>
        </div>
        <Favourite capability={capability} />
      </div>
      <div className="mt-auto flex flex-wrap items-center gap-2">
        <Pill tone={CATEGORY_TONE[capability.category] ?? "neutral"}>
          {categorySaid(t, capability.category)}
        </Pill>
        {capability.kind === "agent" ? <Pill tone="neutral">{t.catalogue.kinds.agent}</Pill> : null}
        <span className="text-xs text-shell-muted">
          {capability.usage.runs
            ? fill(t.catalogue.runs, { count: capability.usage.runs })
            : t.catalogue.noRun}
        </span>
      </div>
      <Availability capability={capability} />
    </li>
  );
}

const WIDTH = 320;
const HEIGHT = 140;
const BOTTOM = 18;

function UsageChart({ summary }: { summary: CatalogueSummary }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const used = summary.categories.map((c) => c.category);
  const totals = summary.days.map((d) => Object.values(d.runs).reduce((a, b) => a + b, 0));
  const top = Math.max(4, ...totals);
  const slot = WIDTH / Math.max(1, summary.days.length);
  const bar = slot * 0.5;
  const plot = HEIGHT - BOTTOM;
  const day = new Intl.DateTimeFormat(locale === "fr" ? "fr-FR" : "en-GB", {
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
  const { locale } = useLocale();
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
                    {item.title}
                  </Link>
                  <p className="line-clamp-1 text-xs text-shell-muted">{item.summary}</p>
                </div>
                <time dateTime={item.registered_at} className="shrink-0 text-xs text-shell-muted">
                  {new Intl.DateTimeFormat(locale === "fr" ? "fr-FR" : "en-GB", {
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

function Grid({ query, empty }: { query: CatalogueQuery; empty: string }) {
  const t = useDictionary();
  const list = useCapabilities(query);
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
  if (!list.data.length) {
    return (
      <p className="rounded-xl border border-shell-line bg-white px-5 py-6 text-[0.875rem] text-shell-muted" data-testid="catalogue-empty">
        {empty}
      </p>
    );
  }
  return (
    <ul className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3" data-testid="catalogue-grid">
      {list.data.map((capability) => (
        <Card key={capability.key} capability={capability} />
      ))}
    </ul>
  );
}

function Filters({
  summary,
  category,
  setCategory,
  q,
  setQ,
  sort,
  setSort,
}: {
  summary: CatalogueSummary | undefined;
  category: string | null;
  setCategory: (next: string | null) => void;
  q: string;
  setQ: (next: string) => void;
  sort: NonNullable<CatalogueQuery["sort"]>;
  setSort: (next: NonNullable<CatalogueQuery["sort"]>) => void;
}) {
  const t = useDictionary();
  const w = t.catalogue;
  const chip = (active: boolean) =>
    cn(
      "flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[0.8125rem] font-medium",
      active
        ? "border-shell-nav-active bg-brand-violet-soft text-shell-nav-active"
        : "border-shell-line bg-white text-brand-navy hover:bg-shell-canvas",
    );
  return (
    <div className="flex flex-col gap-3 xl:flex-row xl:items-center" data-testid="catalogue-filters">
      <div className="flex flex-wrap gap-2">
        <button type="button" className={chip(category === null)} onClick={() => setCategory(null)} aria-pressed={category === null}>
          {w.all}
          <span className="rounded bg-white/70 px-1 text-xs text-shell-muted">{summary?.total ?? "…"}</span>
        </button>
        {(summary?.categories ?? []).map((c) => (
          <button
            key={c.category}
            type="button"
            className={chip(category === c.category)}
            onClick={() => setCategory(c.category)}
            aria-pressed={category === c.category}
            data-testid={`catalogue-category-${c.category}`}
          >
            {categorySaid(t, c.category)}
            <span className="rounded bg-white/70 px-1 text-xs text-shell-muted">{c.count}</span>
          </button>
        ))}
      </div>
      <div className="flex flex-1 items-center gap-2 xl:justify-end">
        <label className="relative flex min-w-0 flex-1 items-center xl:max-w-64">
          <Search className="absolute left-2.5 size-4 text-shell-muted" aria-hidden="true" />
          <input
            value={q}
            onChange={(event) => setQ(event.target.value)}
            placeholder={w.search}
            aria-label={w.search}
            className="h-9 w-full rounded-lg border border-shell-line bg-white pr-2 pl-8 text-sm text-brand-navy outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40"
            data-testid="catalogue-search"
          />
        </label>
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
  const [category, setCategory] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<NonNullable<CatalogueQuery["sort"]>>("relevant");

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
          {summary.data ? <Stats summary={summary.data} /> : <div className="h-24 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />}
          <Filters
            summary={summary.data}
            category={category}
            setCategory={setCategory}
            q={q}
            setQ={setQ}
            sort={sort}
            setSort={setSort}
          />
          <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
            <Grid
              query={{ view: view === "mine" ? "mine" : "all", category, q, sort }}
              empty={view === "mine" && !category && !q ? w.mineEmpty : w.empty}
            />
            {summary.data ? (
              <div className="flex min-w-0 flex-col gap-4">
                <UsageChart summary={summary.data} />
                <Top summary={summary.data} />
                <Latest summary={summary.data} />
              </div>
            ) : null}
          </div>
          <section className="flex flex-wrap items-center gap-4 rounded-xl bg-brand-violet-soft/60 px-5 py-4" data-testid="catalogue-banner">
            <Gauge className="size-6 shrink-0 text-shell-nav-active" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="font-semibold text-brand-navy">{w.askTitle}</p>
              <p className="text-[0.8125rem] text-shell-muted">{w.askBody}</p>
            </div>
            <Link href={routes.intentionNew()} className={buttonVariants({ variant: "outline" })}>
              {w.ask}
              <ArrowRight className="size-4" aria-hidden="true" />
            </Link>
          </section>
        </div>
      )}
    </PageContainer>
  );
}
