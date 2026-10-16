"use client";

import {
  CalendarDays,
  ChartLine,
  ChevronRight,
  CircleCheck,
  Copy,
  Ellipsis,
  FileText,
  type LucideIcon,
  SearchX,
  Sparkles,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useMemo, useState } from "react";

import { cn } from "cn";

import { EntityContext } from "@/components/environment/entity-context";
import { EntityHistory, RemovedEntity } from "@/components/environment/entity-history";
import { IncidentAnalysis } from "@/components/environment/incident-analysis";
import { EntityQuality } from "@/components/environment/knowledge-quality";
import { TwinProvenance } from "@/components/environment/twin";
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
import { BackHome, PageContainer } from "@/components/shell/page-container";
import {
  ActivityCard,
  ConfigurationTab,
  DeploymentsTab,
  LogsTab,
  Mentions,
  MetricsTab,
  OpenWork,
  OverviewTiles,
  type PeriodDays,
} from "@/components/environment/entity-tabs";
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

// One period for the whole page: its events, its figures, its chart. (The
// figures and chart were 30 days whatever was chosen — « 618 changements »
// under « 7 derniers jours », 2026-10-09.)
const PERIODS = { "7d": 7, "30d": 30, "90d": 90 } as const;
type Period = keyof typeof PERIODS;

const HOUR = 3_600_000;


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
  // Its state deduced from what runs it, no tool measuring it.
  deduced: boolean;
  version?: string;
  description?: string;
  owner: { name: string; subtitle: string; href?: string } | null;
  team: { name: string; subtitle: string; href?: string } | null;
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
  const notFound = (
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
  );

  return (
    <PageContainer>
      <BackHome />
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
        // A thing no source shows any more: its course remains (LEKA-383).
        isEntityId(id) ? (
          <RemovedEntity entityId={id} fallback={notFound} />
        ) : (
          notFound
        )
      ) : sheet.isError ? (
        <ErrorState error={sheet.error} onRetry={() => void sheet.refetch()} />
      ) : model ? (
        <Sheet model={model} data={sheet.data as EntitySheet} tab={tab} />
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
    deduced: sheet.deduced ?? false,
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

function Sheet({ model, data, tab }: { model: SheetModel; data: EntitySheet; tab: string }) {
  const t = useDictionary();
  const w = t.environment.sheet;
  const [period, setPeriod] = useState<Period>("30d");
  const events = useMemo(() => {
    const since = Date.now() - PERIODS[period] * 24 * HOUR;
    return model.events.filter((event) => Date.parse(event.at) >= since);
  }, [model.events, period]);

  let body: React.ReactNode;
  if (tab === "overview") {
    body = <Overview model={model} events={events} days={PERIODS[period]} />;
  } else if (tab === "dependencies") {
    body = (
      <Card title={fill(w.dependencies.title, { count: model.dependencies.length })}>
        <Dependencies rows={model.dependencies} />
      </Card>
    );
  } else if (tab === "incidents") {
    body = (
      <div className="flex flex-col gap-4">
        <Card title={t.tabs.incidents}>
          <EventList rows={model.incidents} empty={w.incidentsEmpty} detailed />
        </Card>
        <OpenWork entityId={model.id} />
      </div>
    );
  } else if (tab === "documentation") {
    body = (
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title={t.tabs.documentation}>
          <Documents rows={model.documents} />
        </Card>
        <Mentions entityId={model.id} />
      </div>
    );
  } else if (tab === "metrics") {
    body = <MetricsTab entityId={model.id} />;
  } else if (tab === "deployments") {
    body = <DeploymentsTab entityId={model.id} />;
  } else if (tab === "logs") {
    body = <LogsTab entityId={model.id} />;
  } else if (tab === "configuration") {
    body = <ConfigurationTab sheet={data} />;
  } else if (tab === "context") {
    body = <EntityContext entityId={model.id} entityName={model.name} />;
  } else if (tab === "history") {
    body = <EntityHistory entityId={model.id} name={model.name} />;
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
      <Header
        model={model}
        period={period}
        onPeriod={setPeriod}
        provenance={<TwinProvenance twin={data.twin} sources={data.sources ?? []} />}
      />
      <RouteTabs />
      {body}
    </>
  );
}

function Header({
  model,
  period,
  onPeriod,
  provenance,
}: {
  model: SheetModel;
  period: Period;
  onPeriod: (period: Period) => void;
  /** Its state in the Digital Twin, where it comes from (LEKA-442). */
  provenance?: React.ReactNode;
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
            {model.deduced ? (
              <span
                className="rounded-md bg-state-warning/10 px-2 py-0.5 text-xs text-state-warning"
                title={w.deducedWhy}
                data-testid="sheet-deduced"
              >
                {w.deduced}
              </span>
            ) : null}
            {model.version ? (
              <span className="rounded-md border border-shell-line px-2 py-0.5 text-xs text-brand-navy">
                {model.version}
              </span>
            ) : null}
          </div>
          {provenance}
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
            onValueChange={(value) => onPeriod((value as Period | null) ?? "30d")}
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

function Overview({
  model,
  events,
  days,
}: {
  model: SheetModel;
  events: EventRow[];
  days: PeriodDays;
}) {
  const t = useDictionary();
  const w = t.environment.sheet;
  // What needs someone, apart from what is only worth knowing.
  const pressing = model.attention.filter((row) => row.level !== "info");
  const known = model.general.filter((row) => row.value !== w.general.unknown);
  const unknown = model.general.filter((row) => row.value === w.general.unknown);
  return (
    <div className="flex flex-col gap-4">
      {/* As many columns as figures with something to say, and the incident's. */}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-[repeat(auto-fit,minmax(11rem,1fr))]">
        <OverviewTiles entityId={model.id} days={days} />
        <ActiveIncident model={model} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <ActivityCard entityId={model.id} days={days} />
        <Card
          title={
            pressing.length
              ? fill(w.attention, { count: pressing.length })
              : model.attention.length
                ? w.attentionKnown
                : w.attentionNone
          }
          icon={
            <span
              aria-hidden="true"
              className={cn(
                "size-2.5 rounded-full",
                pressing.length
                  ? "bg-state-danger"
                  : model.attention.length
                    ? "bg-state-info"
                    : "bg-state-success",
              )}
            />
          }
          action={
            pressing.length ? (
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
            {known.map((row) => (
              <div key={row.label} className="contents">
                <dt className="text-shell-muted">{row.label}</dt>
                <dd className="min-w-0 truncate text-brand-navy">{row.value}</dd>
              </div>
            ))}
          </dl>
          {/* What no source says yet, said once in words (LEKA-438). */}
          {unknown.length ? (
            <p className="mt-3 text-xs text-shell-muted" data-testid="general-unknown">
              {fill(w.general.notYet, { fields: unknown.map((row) => row.label.toLowerCase()).join(", ") })}
            </p>
          ) : null}
        </Card>
      </div>

      {/* How far what LEKA knows of it can be trusted (LEKA-381). */}
      <EntityQuality id={model.id} />

      {/* An incident's analysis; elsewhere « Demander à LEKA », above, asks. */}
      {model.type === "incident" ? <IncidentAnalysis id={model.id} /> : null}
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
            <ChevronRight className="rtl:-scale-x-100 size-4 shrink-0 text-shell-muted" aria-hidden="true" />
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
