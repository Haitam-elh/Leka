"use client";

import {
  Activity,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  CalendarDays,
  ChartLine,
  ChevronRight,
  CircleCheck,
  Clock,
  Copy,
  Ellipsis,
  FileText,
  Gauge,
  type LucideIcon,
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

import { EntityContext } from "@/components/environment/entity-context";
import { Sparkline } from "@/components/knowledge/entity-detail-panel";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { timeAgo } from "@/components/knowledge/time";
import {
  AttentionList,
  type AttentionRow,
  attentionRows,
  Card,
  CardLink,
  entityHref,
  EventList,
  type EventRow,
  eventRows,
  IconTile,
  Logo,
  typeIcon,
  typeLabel,
} from "@/components/environment/parts";
import { PageContainer } from "@/components/shell/page-container";
import { RouteTabs } from "@/components/shell/route-tabs";
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
  type EnvironmentStatus,
  isEntityId,
} from "@/lib/environment";
import { useEntitySheet } from "@/lib/environment-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { buildBreadcrumb } from "@/lib/navigation/breadcrumb";
import { useNamePage } from "@/lib/navigation/page-name";
import { matchRoute } from "@/lib/navigation/active";
import { notify } from "@/lib/notify";

/**
 * One entity's sheet, laid out as docs/product/mockups/11-environnement-
 * fiche-service.jpeg (LEKA-359). One model, two fillings: the entity as
 * resolution and enrichment made it — its metrics and LEKA's analysis
 * saying what they wait for — or, for the example "Mon environnement"
 * shows an empty workspace, the mockup's Payment API under the "Exemple"
 * banner.
 */

const PERIODS = { "24h": 24, "7d": 24 * 7, "30d": 24 * 30 } as const;
type Period = keyof typeof PERIODS;

const HOUR = 3_600_000;


const METRICS: { id: string; icon: LucideIcon }[] = [
  { id: "latency", icon: Clock },
  { id: "errors", icon: TriangleAlert },
  { id: "requests", icon: Activity },
  { id: "availability", icon: Gauge },
];

interface Metric {
  id: string;
  icon: LucideIcon;
  label: string;
  value?: string;
  delta?: { text: string; up: boolean };
  /** Whether where it goes is good news: sets the colours. */
  good?: boolean;
  series?: readonly number[];
}

interface Dependency {
  key: string;
  name: string;
  icon?: LucideIcon;
  source?: string;
  status: EnvironmentStatus | null;
  note: string;
  href?: string;
}

/** Everything the sheet shows. */
interface SheetModel {
  id: string;
  key: string;
  type: string;
  name: string;
  typeLine: string;
  status: EnvironmentStatus | null;
  version?: string;
  description?: string;
  owner: { name: string; subtitle: string; href?: string } | null;
  team: { name: string; subtitle: string; href?: string } | null;
  metrics: Metric[];
  incident: { title: string; since: string; href: string } | null;
  attention: AttentionRow[];
  events: EventRow[];
  incidents: EventRow[];
  dependencies: Dependency[];
  documents: { key: string; name: string; href?: string }[];
  general: { label: string; value: React.ReactNode }[];
}

export function EntitySheetScreen() {
  const t = useDictionary();
  const params = useParams<{ entityId: string }>();
  const pathname = usePathname() ?? "/";
  const id = params.entityId ?? "";
  const sheet = useEntitySheet(id);
  const model = useSheetModel(sheet.data);
  const crumbs = buildBreadcrumb(pathname, t, model ? () => model.name : undefined);
  useNamePage(pathname, model?.name);
  const tab = matchRoute(pathname)?.tab ?? "overview";
  const missing =
    !isEntityId(id) || (sheet.error instanceof ApiError && sheet.error.status === 404);

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
      ) : model ? (
        <Sheet model={model} tab={tab} />
      ) : (
        <div className="h-96 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />
      )}
    </PageContainer>
  );
}

function useSheetModel(sheet: EntitySheet | undefined): SheetModel | undefined {
  const t = useDictionary();
  return useMemo(() => (sheet ? realModel(t, sheet) : undefined), [sheet, t]);
}

function realModel(t: ReturnType<typeof useDictionary>, sheet: EntitySheet): SheetModel {
  const w = t.environment.sheet;
  const entity = sheet.entity;
  const enriched = Object.fromEntries(entity.enriched.map((a) => [a.attribute, a.value]));
  const version = entity.attributes.version;
  const description = entity.attributes.description;
  const state = entity.attributes.state;
  const lifecycle = enriched.lifecycle;
  const last = enriched.last_activity_at;
  const open = sheet.incidents.find((incident) => incident.kind === "incident");
  const infrastructure = sheet.dependencies.filter((d) => d.entity.type === "infra_resource");
  const data = sheet.dependencies.filter((d) => d.entity.type === "database");
  const relations = t.environment.relations as Record<string, { out: string; in: string }>;
  const unknown = w.general.unknown;

  return {
    id: entity.id,
    key: entity.key,
    type: entity.type,
    name: entity.name,
    typeLine: [typeLabel(t, entity.type), sheet.environment].filter(Boolean).join(" · "),
    status: sheet.status as EnvironmentStatus | null,
    version: typeof version === "string" ? version : undefined,
    description: typeof description === "string" && description ? description : undefined,
    owner: sheet.owner
      ? {
          name: sheet.owner.entity.name,
          subtitle: fill(w.maintainer, { score: Math.round(sheet.owner.confidence * 100) }),
          href: entityHref(sheet.owner.entity),
        }
      : null,
    team: sheet.team
      ? {
          name: sheet.team.entity.name,
          subtitle: sheet.team.members
            ? fill(w.members, { count: sheet.team.members })
            : sheet.team.origin === "stated"
              ? w.teamStated
              : fill(w.teamInferred, { score: Math.round(sheet.team.confidence * 100) }),
          href: entityHref(sheet.team.entity),
        }
      : null,
    metrics: METRICS.map((metric) => ({
      ...metric,
      label: (w.metrics as Record<string, string>)[metric.id],
    })),
    incident: open
      ? { title: open.entity.name, since: open.at, href: entityHref(open.entity) }
      : null,
    attention: attentionRows(t, sheet.attention),
    events: eventRows(t, sheet.events),
    incidents: eventRows(t, sheet.incidents),
    dependencies: sheet.dependencies.map((link) => {
      const relation = relations[link.type] ?? relations.other;
      const notes = [link.direction === "out" ? relation.out : relation.in];
      if (link.origin === "inferred") {
        notes.push(fill(w.dependencies.inferred, { score: Math.round(link.confidence * 100) }));
      }
      if (link.cross_source) notes.push(w.dependencies.crossSource);
      return {
        key: `${link.type}-${link.direction}-${link.entity.id}`,
        name: link.entity.name,
        icon: typeIcon(link.entity.type),
        status: link.status as EnvironmentStatus | null,
        note: notes.join(" · "),
        href: entityHref(link.entity),
      };
    }),
    documents: sheet.documents.map((document) => ({
      key: document.id,
      name: document.name,
      href: entityHref(document),
    })),
    general: [
      { label: w.general.type, value: typeLabel(t, entity.type) },
      { label: w.general.environment, value: sheet.environment ?? unknown },
      { label: w.general.version, value: typeof version === "string" ? version : unknown },
      { label: w.general.state, value: typeof state === "string" ? state : unknown },
      {
        label: w.general.lifecycle,
        value:
          typeof lifecycle === "string"
            ? ((w.lifecycles as Record<string, string>)[lifecycle] ?? lifecycle)
            : unknown,
      },
      {
        label: w.general.lastActivity,
        value: typeof last === "string" ? timeAgo(t, last) : unknown,
      },
      {
        label: w.general.infrastructure,
        value: infrastructure.length
          ? infrastructure.map((d) => d.entity.name).join(", ")
          : unknown,
      },
      {
        label: w.general.data,
        value: data.length ? data.map((d) => d.entity.name).join(", ") : unknown,
      },
      {
        label: w.general.runbook,
        value: sheet.documents[0] ? (
          <Link
            href={entityHref(sheet.documents[0])}
            className="font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          >
            {sheet.documents[0].name}
          </Link>
        ) : (
          unknown
        ),
      },
      {
        label: w.general.sources,
        value: sheet.source_kinds.length ? (
          <span className="flex gap-1.5">
            {sheet.source_kinds.map((kind) => (
              <Logo key={kind} kind={kind} className="size-4" />
            ))}
          </span>
        ) : (
          unknown
        ),
      },
    ],
  };
}

function Sheet({ model, tab }: { model: SheetModel; tab: string }) {
  const t = useDictionary();
  const w = t.environment.sheet;
  const [period, setPeriod] = useState<Period>("7d");
  const events = useMemo(() => {
    const since = Date.now() - PERIODS[period] * HOUR;
    return model.events.filter((event) => Date.parse(event.at) >= since);
  }, [model.events, period]);

  let body: React.ReactNode;
  if (tab === "overview") {
    body = <Overview model={model} events={events} />;
  } else if (tab === "dependencies") {
    body = (
      <Card title={fill(w.dependencies.title, { count: model.dependencies.length })}>
        <Dependencies rows={model.dependencies} />
      </Card>
    );
  } else if (tab === "incidents") {
    body = (
      <Card title={t.tabs.incidents}>
        <EventList rows={model.incidents} empty={w.incidentsEmpty} detailed />
      </Card>
    );
  } else if (tab === "documentation") {
    body = (
      <Card title={t.tabs.documentation}>
        <Documents rows={model.documents} />
      </Card>
    );
  } else if (tab === "context") {
    body = <EntityContext entityId={model.id} entityName={model.name} />;
  } else {
    body = (
      <StatePanel
        icon={ChartLine}
        title={(t.tabs as Record<string, string>)[tab] ?? tab}
        description={(w.tabs as Record<string, string>)[tab]}
        size="section"
        className="rounded-xl border border-shell-line bg-white"
      />
    );
  }

  return (
    <>
      <Header model={model} period={period} onPeriod={setPeriod} />
      <RouteTabs />
      {body}
    </>
  );
}

function Header({
  model,
  period,
  onPeriod,
}: {
  model: SheetModel;
  period: Period;
  onPeriod: (period: Period) => void;
}) {
  const t = useDictionary();
  const w = t.environment.sheet;
  const periods = (Object.keys(PERIODS) as Period[]).map((value) => ({
    value,
    label: w.periods[value],
  }));
  const tone =
    model.status === "incident" ? "danger" : model.status === "attention" ? "warning" : "violet";

  async function copyKey() {
    try {
      await navigator.clipboard.writeText(model.key);
      notify.success({ title: w.copied });
    } catch {
      // A browser that refuses the clipboard: the key is on the page.
    }
  }

  return (
    <div className="mb-5 flex flex-col gap-5 xl:flex-row xl:items-start">
      <div className="flex min-w-0 flex-1 items-start gap-4">
        <IconTile
          icon={typeIcon(model.type)}
          tone={tone}
          className="size-16 rounded-xl [&>svg]:size-8"
        />
        <div className="min-w-0">
          <h1 className="truncate text-[2rem] leading-tight font-bold tracking-[-0.02em] text-brand-navy">
            {model.name}
          </h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[0.875rem] text-shell-muted">
            <span>{model.typeLine}</span>
            {model.status ? <StatusBadge variant={`entity.${model.status}`} dot /> : null}
            {model.version ? (
              <span className="rounded-md border border-shell-line px-2 py-0.5 text-xs text-brand-navy">
                {model.version}
              </span>
            ) : null}
          </div>
          {model.description ? (
            <p className="mt-2 max-w-2xl text-[0.875rem] text-shell-nav-active">
              {model.description}
            </p>
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
              <CalendarDays className="size-4 text-shell-muted" aria-hidden="true" />
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
          <Person
            label={w.owner}
            person={model.owner}
            empty={w.noOwner}
            avatar={model.owner?.name.slice(0, 1).toUpperCase()}
          />
          <Person label={w.team} person={model.team} empty={w.noTeam} />
        </dl>
      </div>
    </div>
  );
}

function Person({
  label,
  person,
  empty,
  avatar,
}: {
  label: string;
  person: { name: string; subtitle: string; href?: string } | null;
  empty: string;
  avatar?: string;
}) {
  return (
    <div>
      <dt className="text-shell-muted">{label}</dt>
      <dd className="mt-1 flex items-center gap-2">
        {person ? (
          <>
            {avatar ? (
              <span className="flex size-8 items-center justify-center rounded-full bg-brand-violet-soft text-xs font-semibold text-shell-nav-active">
                {avatar}
              </span>
            ) : (
              <IconTile icon={Users} tone="violet" className="size-8" />
            )}
            <span>
              {person.href ? (
                <Link
                  href={person.href}
                  className="block font-medium text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                >
                  {person.name}
                </Link>
              ) : (
                <span className="block font-medium text-brand-navy">{person.name}</span>
              )}
              <span className="block text-xs text-shell-muted">{person.subtitle}</span>
            </span>
          </>
        ) : (
          <span className="text-shell-muted">{empty}</span>
        )}
      </dd>
    </div>
  );
}

function MetricTiles({ model }: { model: SheetModel }) {
  const t = useDictionary();
  const w = t.environment.sheet;
  return (
    <>
      {model.metrics.map((metric) => (
        <div
          key={metric.id}
          className="rounded-xl border border-shell-line bg-white p-4"
          data-testid={`metric-${metric.id}`}
        >
          <p className="flex items-center gap-2 text-[0.8125rem] text-brand-navy">
            <metric.icon className="size-4 text-shell-muted" aria-hidden="true" />
            {metric.label}
          </p>
          {metric.value ? (
            <>
              <p
                className={cn(
                  "mt-2 text-[1.75rem] leading-8 font-bold",
                  metric.good ? "text-brand-navy" : "text-state-danger",
                )}
              >
                {metric.value}
              </p>
              <div className="mt-1 flex items-end justify-between gap-2">
                {metric.delta ? (
                  <span
                    className={cn(
                      "flex items-center gap-1 text-[0.8125rem] font-medium",
                      metric.good ? "text-state-success" : "text-state-danger",
                    )}
                  >
                    {metric.delta.text}
                    {metric.delta.up ? (
                      <ArrowUp className="size-3.5" aria-hidden="true" />
                    ) : (
                      <ArrowDown className="size-3.5" aria-hidden="true" />
                    )}
                  </span>
                ) : null}
                {metric.series ? (
                  <Sparkline
                    values={metric.series}
                    tone={metric.good ? "success" : "danger"}
                    className="h-8 w-28"
                  />
                ) : null}
              </div>
            </>
          ) : (
            <>
              <p className="mt-2 text-[1.75rem] leading-8 font-bold text-shell-muted">—</p>
              <p className="mt-1 text-xs text-shell-muted">{w.metrics.notMeasured}</p>
            </>
          )}
        </div>
      ))}
    </>
  );
}

function PerformanceCard() {
  const t = useDictionary();
  const w = t.environment.sheet;
  return (
    <Card
      title={w.performance.title}
      icon={<IconTile icon={ChartLine} tone="violet" className="size-9" />}
    >
      <p className="py-10 text-center text-[0.8125rem] text-shell-muted">{w.performance.empty}</p>
    </Card>
  );
}

function Overview({ model, events }: { model: SheetModel; events: EventRow[] }) {
  const t = useDictionary();
  const w = t.environment.sheet;
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-[repeat(4,minmax(0,1fr))_minmax(0,1.4fr)]">
        <MetricTiles model={model} />
        <ActiveIncident model={model} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <PerformanceCard />
        <Card
          title={
            model.attention.length
              ? fill(w.attention, { count: model.attention.length })
              : w.attentionNone
          }
          icon={
            <span
              aria-hidden="true"
              className={cn(
                "size-2.5 rounded-full",
                model.attention.length ? "bg-state-danger" : "bg-state-success",
              )}
            />
          }
          action={
            model.attention.length ? (
              <CardLink href={routes.approvals()}>{t.environment.kpi.seeAll}</CardLink>
            ) : null
          }
        >
          <AttentionList rows={model.attention} empty={t.environment.attention.empty} />
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card
          title={w.events.title}
          action={<CardLink href={routes.activity()}>{t.environment.kpi.seeAll}</CardLink>}
        >
          <EventList rows={events} empty={w.events.empty} detailed />
        </Card>
        <Card
          title={fill(w.dependencies.title, { count: model.dependencies.length })}
          action={
            <CardLink href={routes.environmentGraph(model.id)}>{w.dependencies.seeGraph}</CardLink>
          }
        >
          <Dependencies rows={model.dependencies} max={5} />
        </Card>
        <Card title={w.general.title}>
          <dl className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-3 gap-y-2.5 text-[0.8125rem]">
            {model.general.map((row) => (
              <div key={row.label} className="contents">
                <dt className="text-shell-muted">{row.label}</dt>
                <dd className="min-w-0 truncate text-brand-navy">{row.value}</dd>
              </div>
            ))}
          </dl>
        </Card>
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

function ActiveIncident({ model }: { model: SheetModel }) {
  const t = useDictionary();
  const w = t.environment.sheet.incident;
  const open = model.incident;
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
        <span aria-hidden="true" className="size-3 rounded-full bg-state-danger" />
        {w.active}
      </p>
      <p className="mt-2 text-[0.875rem] text-brand-navy">{open.title}</p>
      <div className="mt-3 flex items-center justify-between gap-3 text-[0.8125rem]">
        <span className="text-shell-muted">{fill(w.since, { ago: timeAgo(t, open.since) })}</span>
        <CardLink href={open.href}>{w.see}</CardLink>
      </div>
    </div>
  );
}

function Dependencies({ rows, max }: { rows: readonly Dependency[]; max?: number }) {
  const t = useDictionary();
  const shown = max ? rows.slice(0, max) : rows;
  if (shown.length === 0) {
    return (
      <p className="py-4 text-center text-[0.8125rem] text-shell-muted">
        {t.environment.sheet.dependencies.empty}
      </p>
    );
  }
  return (
    <ul className="divide-y divide-shell-line/60">
      {shown.map((row) => {
        const Icon = row.icon;
        return (
          <li
            key={row.key}
            className="flex items-center gap-3 py-2 text-[0.8125rem]"
            data-testid="dependency-row"
          >
            {row.source ? (
              <Logo kind={row.source} className="size-5 shrink-0" />
            ) : Icon ? (
              <Icon className="size-4 shrink-0 text-shell-nav-active" aria-hidden="true" />
            ) : null}
            <span className="min-w-0 flex-1">
              {row.href ? (
                <Link
                  href={row.href}
                  className="block truncate font-medium text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                >
                  {row.name}
                </Link>
              ) : (
                <span className="block truncate font-medium text-brand-navy">{row.name}</span>
              )}
              <span className="block truncate text-xs text-shell-muted">{row.note}</span>
            </span>
            {row.status ? <StatusBadge variant={`entity.${row.status}`} size="sm" /> : null}
            <ChevronRight className="size-4 shrink-0 text-shell-muted" aria-hidden="true" />
          </li>
        );
      })}
    </ul>
  );
}

function Documents({ rows }: { rows: SheetModel["documents"] }) {
  const t = useDictionary();
  if (rows.length === 0) {
    return (
      <p className="py-4 text-center text-[0.8125rem] text-shell-muted">
        {t.environment.sheet.documentsEmpty}
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {rows.map((document) => (
        <li key={document.key} className="flex items-center gap-2 text-[0.8125rem]">
          <FileText className="size-4 text-shell-nav-active" aria-hidden="true" />
          {document.href ? (
            <Link
              href={document.href}
              className="font-medium text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
            >
              {document.name}
            </Link>
          ) : (
            <span className="font-medium text-brand-navy">{document.name}</span>
          )}
        </li>
      ))}
    </ul>
  );
}
