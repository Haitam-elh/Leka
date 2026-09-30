"use client";

import {
  Activity,
  ArrowRight,
  ChartLine,
  CircleCheck,
  Clock,
  Copy,
  Ellipsis,
  FileText,
  Gauge,
  OctagonAlert,
  SearchX,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useMemo, useState } from "react";

import { cn } from "cn";

import { StatusBadge } from "@/components/knowledge/status-badge";
import { timeAgo } from "@/components/knowledge/time";
import {
  AttentionList,
  Card,
  CardLink,
  entityHref,
  EventList,
  IconTile,
  typeIcon,
  typeLabel,
} from "@/components/environment/parts";
import { PageContainer } from "@/components/shell/page-container";
import { RouteTabs } from "@/components/shell/route-tabs";
import { SourceLogo } from "@/components/sources/source-logo";
import { ErrorState } from "@/components/states/error-state";
import { StatePanel } from "@/components/states/state-panel";
import { buttonVariants } from "@/components/ui/button";
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
import { ApiError } from "@/lib/api";
import {
  type EntitySheet,
  type EnvironmentEvent,
  type EnvironmentStatus,
  isEntityId,
  typeSegment,
} from "@/lib/environment";
import { useEntitySheet } from "@/lib/environment-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { buildBreadcrumb } from "@/lib/navigation/breadcrumb";
import { matchRoute } from "@/lib/navigation/active";
import { notify } from "@/lib/notify";
import type { SourceKind } from "@/lib/sources";

/**
 * One entity's sheet, laid out as docs/product/mockups/11-environnement-
 * fiche-service.jpeg (LEKA-359): who owns it, its state, what threatens it,
 * what moved around it, what it depends on — each from what the sources
 * said, resolved and enriched. Its metrics and LEKA's analysis have their
 * places, and say what they wait for.
 */

const PERIODS = { "24h": 24, "7d": 24 * 7, "30d": 24 * 30 } as const;
type Period = keyof typeof PERIODS;

const HOUR = 3_600_000;

export function EntitySheetScreen() {
  const t = useDictionary();
  const params = useParams<{ entityId: string }>();
  const pathname = usePathname() ?? "/";
  const id = params.entityId ?? "";
  const valid = isEntityId(id);
  const sheet = useEntitySheet(id);
  const name = sheet.data?.entity.name;
  const crumbs = buildBreadcrumb(pathname, t, name ? () => name : undefined);
  const tab = matchRoute(pathname)?.tab ?? "overview";
  const missing = !valid || (sheet.error instanceof ApiError && sheet.error.status === 404);

  return (
    <PageContainer>
      <nav aria-label={t.shell.breadcrumb} className="mb-3">
        <ol className="flex flex-wrap items-center gap-2 text-[0.8125rem] text-shell-muted">
          {crumbs.map((crumb, index) => (
            <li key={`${crumb.label}-${index}`} className="flex items-center gap-2">
              {index > 0 ? <span aria-hidden="true">›</span> : null}
              {crumb.href ? (
                <Link
                  href={crumb.href}
                  className="rounded outline-none hover:text-brand-violet focus-visible:ring-3 focus-visible:ring-brand-violet/40"
                >
                  {crumb.label}
                </Link>
              ) : (
                <span aria-current="page">{crumb.label}</span>
              )}
            </li>
          ))}
        </ol>
      </nav>
      {missing ? (
        <StatePanel
          icon={SearchX}
          title={t.environment.sheet.notFoundTitle}
          description={t.environment.sheet.notFoundBody}
          headingLevel={1}
          testId="route-state-not-found"
          actions={
            <Link href={routes.environment()} className={buttonVariants({ variant: "outline" })}>
              {t.environment.sheet.back}
            </Link>
          }
        />
      ) : sheet.isError ? (
        <ErrorState error={sheet.error} onRetry={() => void sheet.refetch()} />
      ) : sheet.data ? (
        <Sheet sheet={sheet.data} tab={tab} />
      ) : (
        <div className="h-96 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />
      )}
    </PageContainer>
  );
}

function Sheet({ sheet, tab }: { sheet: EntitySheet; tab: string }) {
  const t = useDictionary();
  const [period, setPeriod] = useState<Period>("7d");
  const events = useMemo(() => {
    const since = Date.now() - PERIODS[period] * HOUR;
    return sheet.events.filter((event) => Date.parse(event.at) >= since);
  }, [sheet.events, period]);

  return (
    <>
      <Header sheet={sheet} period={period} onPeriod={setPeriod} />
      <RouteTabs />
      {tab === "overview" ? (
        <Overview sheet={sheet} events={events} />
      ) : tab === "dependencies" ? (
        <Card
          title={fill(t.environment.sheet.dependencies.title, {
            count: sheet.dependencies.length,
          })}
        >
          <Dependencies sheet={sheet} />
        </Card>
      ) : tab === "incidents" ? (
        <Card title={t.tabs.incidents}>
          <EventList
            events={sheet.incidents}
            empty={t.environment.sheet.incidentsEmpty}
            withSource
          />
        </Card>
      ) : tab === "documentation" ? (
        <Card title={t.tabs.documentation}>
          <Documents sheet={sheet} />
        </Card>
      ) : (
        <StatePanel
          icon={ChartLine}
          title={(t.tabs as Record<string, string>)[tab] ?? tab}
          description={(t.environment.sheet.tabs as Record<string, string>)[tab]}
          size="section"
          className="rounded-xl border border-shell-line bg-white"
        />
      )}
    </>
  );
}

function Header({
  sheet,
  period,
  onPeriod,
}: {
  sheet: EntitySheet;
  period: Period;
  onPeriod: (period: Period) => void;
}) {
  const t = useDictionary();
  const w = t.environment.sheet;
  const entity = sheet.entity;
  const status = sheet.status as EnvironmentStatus | null;
  const version = entity.attributes.version;
  const description = entity.attributes.description;
  const periods = (Object.keys(PERIODS) as Period[]).map((value) => ({
    value,
    label: w.periods[value],
  }));

  async function copyKey() {
    try {
      await navigator.clipboard.writeText(entity.key);
      notify.success({ title: w.copied });
    } catch {
      // A browser that refuses the clipboard: the key is on the page.
    }
  }

  return (
    <div className="mb-5 flex flex-col gap-5 xl:flex-row xl:items-start">
      <div className="flex min-w-0 flex-1 items-start gap-4">
        <IconTile
          icon={typeIcon(entity.type)}
          tone={status === "incident" ? "danger" : status === "attention" ? "warning" : "violet"}
          className="size-16 rounded-xl [&>svg]:size-8"
        />
        <div className="min-w-0">
          <h1 className="truncate text-[2rem] leading-tight font-bold tracking-[-0.02em] text-brand-navy">
            {entity.name}
          </h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[0.875rem] text-shell-muted">
            <span>
              {typeLabel(t, entity.type)}
              {sheet.environment ? ` · ${sheet.environment}` : ""}
            </span>
            {status ? <StatusBadge variant={`entity.${status}`} dot /> : null}
            {typeof version === "string" ? (
              <span className="rounded-md border border-shell-line px-2 py-0.5 text-xs text-brand-navy">
                {version}
              </span>
            ) : null}
          </div>
          {typeof description === "string" && description ? (
            <p className="mt-2 max-w-2xl text-[0.875rem] text-shell-nav-active">{description}</p>
          ) : null}
        </div>
      </div>
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2 xl:justify-end">
          <Select
            value={period}
            onValueChange={(value) => onPeriod((value as Period | null) ?? "7d")}
            items={periods}
          >
            <SelectTrigger className="min-w-44" aria-label={w.period}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {periods.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Link
            href={routes.intentionNew()}
            className="flex items-center gap-2 rounded-lg bg-brand-navy px-4 py-2 text-sm font-medium text-white outline-none hover:bg-brand-navy/90 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
          >
            <Sparkles className="size-4" aria-hidden="true" />
            {w.ask}
          </Link>
          <DropdownMenu>
            <DropdownMenuTrigger
              aria-label={w.more}
              className="flex size-9 items-center justify-center rounded-lg border border-shell-line bg-white text-brand-navy outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-brand-violet/40"
            >
              <Ellipsis className="size-4" aria-hidden="true" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-52">
              <DropdownMenuItem onClick={() => void copyKey()}>
                <Copy className="size-4" aria-hidden="true" />
                {w.copyKey}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <dl className="grid grid-cols-2 gap-6 text-[0.8125rem]">
          <div>
            <dt className="text-shell-muted">{w.owner}</dt>
            <dd className="mt-1 flex items-center gap-2">
              {sheet.owner ? (
                <>
                  <span className="flex size-8 items-center justify-center rounded-full bg-brand-violet-soft text-xs font-semibold text-shell-nav-active">
                    {sheet.owner.entity.name.slice(0, 1).toUpperCase()}
                  </span>
                  <span>
                    <Link
                      href={entityHref(sheet.owner.entity)}
                      className="block font-medium text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                    >
                      {sheet.owner.entity.name}
                    </Link>
                    <span className="block text-xs text-shell-muted">
                      {fill(w.maintainer, { score: Math.round(sheet.owner.confidence * 100) })}
                    </span>
                  </span>
                </>
              ) : (
                <span className="text-shell-muted">{w.noOwner}</span>
              )}
            </dd>
          </div>
          <div>
            <dt className="text-shell-muted">{w.team}</dt>
            <dd className="mt-1 flex items-center gap-2">
              {sheet.team ? (
                <>
                  <IconTile icon={Users} tone="violet" className="size-8" />
                  <span>
                    <Link
                      href={entityHref(sheet.team.entity)}
                      className="block font-medium text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                    >
                      {sheet.team.entity.name}
                    </Link>
                    <span className="block text-xs text-shell-muted">
                      {sheet.team.members
                        ? fill(w.members, { count: sheet.team.members })
                        : sheet.team.origin === "stated"
                          ? w.teamStated
                          : fill(w.teamInferred, {
                              score: Math.round(sheet.team.confidence * 100),
                            })}
                    </span>
                  </span>
                </>
              ) : (
                <span className="text-shell-muted">{w.noTeam}</span>
              )}
            </dd>
          </div>
        </dl>
      </div>
    </div>
  );
}

function Overview({ sheet, events }: { sheet: EntitySheet; events: EnvironmentEvent[] }) {
  const t = useDictionary();
  const w = t.environment.sheet;
  const metrics = [
    { id: "latency", icon: Clock, label: w.metrics.latency },
    { id: "errors", icon: TriangleAlert, label: w.metrics.errors },
    { id: "requests", icon: Activity, label: w.metrics.requests },
    { id: "availability", icon: Gauge, label: w.metrics.availability },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-[repeat(4,minmax(0,1fr))_minmax(0,1.4fr)]">
        {metrics.map((metric) => (
          <div
            key={metric.id}
            className="rounded-xl border border-shell-line bg-white p-4"
            data-testid={`metric-${metric.id}`}
          >
            <p className="flex items-center gap-2 text-[0.8125rem] text-brand-navy">
              <metric.icon className="size-4 text-shell-muted" aria-hidden="true" />
              {metric.label}
            </p>
            <p className="mt-2 text-[1.75rem] leading-8 font-bold text-shell-muted">—</p>
            <p className="mt-1 text-xs text-shell-muted">{w.metrics.notMeasured}</p>
          </div>
        ))}
        <ActiveIncident sheet={sheet} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Card
          title={w.performance.title}
          icon={<IconTile icon={ChartLine} tone="violet" className="size-9" />}
        >
          <p className="py-10 text-center text-[0.8125rem] text-shell-muted">
            {w.performance.empty}
          </p>
        </Card>
        <Card
          title={
            sheet.attention.length
              ? fill(w.attention, { count: sheet.attention.length })
              : w.attentionNone
          }
          icon={
            <span
              aria-hidden="true"
              className={cn(
                "size-2.5 rounded-full",
                sheet.attention.length ? "bg-state-danger" : "bg-state-success",
              )}
            />
          }
        >
          <AttentionList points={sheet.attention} empty={t.environment.attention.empty} />
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title={w.events.title}>
          <EventList events={events} empty={w.events.empty} withSource />
        </Card>
        <Card
          title={fill(w.dependencies.title, { count: sheet.dependencies.length })}
          action={
            <CardLink
              href={routes.entity(typeSegment(sheet.entity.type), sheet.entity.id, "dependencies")}
            >
              {w.dependencies.seeGraph}
            </CardLink>
          }
        >
          <Dependencies sheet={sheet} max={5} />
        </Card>
        <General sheet={sheet} />
      </div>

      <section className="flex flex-col gap-4 rounded-xl bg-shell-highlight px-6 py-5 lg:flex-row lg:items-center">
        <IconTile icon={ShieldCheck} tone="violet" className="size-11" />
        <div className="flex-1">
          <h2 className="text-[1.0625rem] font-semibold text-brand-navy">{w.analysis.title}</h2>
          <p className="text-[0.8125rem] text-shell-muted">{w.analysis.body}</p>
        </div>
        <Link
          href={routes.intentionNew()}
          className="flex items-center gap-2 rounded-lg border border-brand-navy/20 bg-white px-4 py-2 text-sm font-medium text-brand-navy outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        >
          {w.analysis.action}
          <ArrowRight className="size-4" aria-hidden="true" />
        </Link>
      </section>
    </div>
  );
}

function ActiveIncident({ sheet }: { sheet: EntitySheet }) {
  const t = useDictionary();
  const w = t.environment.sheet.incident;
  const open = sheet.incidents.find((incident) => incident.kind === "incident");
  if (!open) {
    return (
      <div
        className="rounded-xl border border-shell-line bg-white p-4"
        data-testid="active-incident"
      >
        <p className="flex items-center gap-2 text-[0.9375rem] font-semibold text-brand-navy">
          <CircleCheck className="size-4 text-state-success" aria-hidden="true" />
          {w.none}
        </p>
        <p className="mt-2 text-[0.8125rem] text-shell-muted">{w.noneBody}</p>
      </div>
    );
  }
  return (
    <div
      className="rounded-xl border border-state-danger/40 bg-state-danger-soft/60 p-4"
      data-testid="active-incident"
    >
      <p className="flex items-center gap-2 text-[0.9375rem] font-semibold text-state-danger">
        <OctagonAlert className="size-4" aria-hidden="true" />
        {w.active}
      </p>
      <p className="mt-2 truncate text-[0.875rem] text-brand-navy">{open.entity.name}</p>
      <div className="mt-3 flex items-center justify-between gap-3 text-[0.8125rem]">
        <span className="text-shell-muted">{fill(w.since, { ago: timeAgo(t, open.at) })}</span>
        <CardLink href={entityHref(open.entity)}>{w.see}</CardLink>
      </div>
    </div>
  );
}

function Dependencies({ sheet, max }: { sheet: EntitySheet; max?: number }) {
  const t = useDictionary();
  const w = t.environment;
  const shown = max ? sheet.dependencies.slice(0, max) : sheet.dependencies;
  if (shown.length === 0) {
    return (
      <p className="py-4 text-center text-[0.8125rem] text-shell-muted">
        {w.sheet.dependencies.empty}
      </p>
    );
  }
  return (
    <ul className="divide-y divide-shell-line/60">
      {shown.map((link) => {
        const relation =
          (w.relations as Record<string, { out: string; in: string }>)[link.type] ??
          w.relations.other;
        const Icon = typeIcon(link.entity.type);
        return (
          <li
            key={`${link.type}-${link.direction}-${link.entity.id}`}
            className="flex items-center gap-3 py-2 text-[0.8125rem]"
            data-testid="dependency-row"
          >
            <Icon className="size-4 shrink-0 text-shell-nav-active" aria-hidden="true" />
            <span className="min-w-0 flex-1">
              <Link
                href={entityHref(link.entity)}
                className="block truncate font-medium text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
              >
                {link.entity.name}
              </Link>
              <span className="block truncate text-xs text-shell-muted">
                {link.direction === "out" ? relation.out : relation.in}
                {link.origin === "inferred"
                  ? ` · ${fill(w.sheet.dependencies.inferred, {
                      score: Math.round(link.confidence * 100),
                    })}`
                  : ""}
                {link.cross_source ? ` · ${w.sheet.dependencies.crossSource}` : ""}
              </span>
            </span>
            {link.status ? (
              <StatusBadge variant={`entity.${link.status as EnvironmentStatus}`} size="sm" />
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function Documents({ sheet }: { sheet: EntitySheet }) {
  const t = useDictionary();
  if (sheet.documents.length === 0) {
    return (
      <p className="py-4 text-center text-[0.8125rem] text-shell-muted">
        {t.environment.sheet.documentsEmpty}
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {sheet.documents.map((document) => (
        <li key={document.id} className="flex items-center gap-2 text-[0.8125rem]">
          <FileText className="size-4 text-shell-nav-active" aria-hidden="true" />
          <Link
            href={entityHref(document)}
            className="font-medium text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          >
            {document.name}
          </Link>
        </li>
      ))}
    </ul>
  );
}

function General({ sheet }: { sheet: EntitySheet }) {
  const t = useDictionary();
  const w = t.environment.sheet.general;
  const enriched = Object.fromEntries(sheet.entity.enriched.map((a) => [a.attribute, a.value]));
  const lifecycle = enriched.lifecycle;
  const last = enriched.last_activity_at;
  const state = sheet.entity.attributes.state;
  const infrastructure = sheet.dependencies.filter((d) => d.entity.type === "infra_resource");
  const data = sheet.dependencies.filter((d) => d.entity.type === "database");
  const rows: { label: string; value: React.ReactNode }[] = [
    { label: w.type, value: typeLabel(t, sheet.entity.type) },
    { label: w.environment, value: sheet.environment ?? w.unknown },
    {
      label: w.version,
      value:
        typeof sheet.entity.attributes.version === "string"
          ? sheet.entity.attributes.version
          : w.unknown,
    },
    { label: w.state, value: typeof state === "string" ? state : w.unknown },
    {
      label: w.lifecycle,
      value:
        typeof lifecycle === "string"
          ? ((t.environment.sheet.lifecycles as Record<string, string>)[lifecycle] ?? lifecycle)
          : w.unknown,
    },
    { label: w.lastActivity, value: typeof last === "string" ? timeAgo(t, last) : w.unknown },
    {
      label: w.infrastructure,
      value: infrastructure.length
        ? infrastructure.map((d) => d.entity.name).join(", ")
        : w.unknown,
    },
    { label: w.data, value: data.length ? data.map((d) => d.entity.name).join(", ") : w.unknown },
    {
      label: w.runbook,
      value: sheet.documents[0] ? (
        <Link
          href={entityHref(sheet.documents[0])}
          className="font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        >
          {sheet.documents[0].name}
        </Link>
      ) : (
        w.unknown
      ),
    },
    {
      label: w.sources,
      value: sheet.source_kinds.length ? (
        <span className="flex gap-1.5">
          {sheet.source_kinds.map((kind) => (
            <SourceLogo key={kind} kind={kind as SourceKind} className="size-4" />
          ))}
        </span>
      ) : (
        w.unknown
      ),
    },
  ];
  return (
    <Card title={w.title}>
      <dl className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-3 gap-y-2 text-[0.8125rem]">
        {rows.map((row) => (
          <div key={row.label} className="contents">
            <dt className="text-shell-muted">{row.label}</dt>
            <dd className="min-w-0 truncate text-brand-navy">{row.value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}
