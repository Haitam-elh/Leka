"use client";

import {
  ArrowRight,
  CircleCheck,
  CircleHelp,
  FileClock,
  Layers,
  Lightbulb,
  List,
  Map as MapIcon,
  Network,
  Plus,
  TriangleAlert,
  Waypoints,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { cn } from "cn";

import { KnowledgeTable, type KnowledgeColumn } from "@/components/knowledge/knowledge-table";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { TONES } from "@/components/knowledge/status";
import { timeAgo } from "@/components/knowledge/time";
import { Cartography, LAYERS, type Layer } from "@/components/environment/cartography";
import {
  AttentionList,
  Card,
  CardLink,
  entityHref,
  EventList,
  IconTile,
  type TileTone,
  typeLabel,
} from "@/components/environment/parts";
import { PageContainer } from "@/components/shell/page-container";
import { ConnectedSources } from "@/components/sources/connected-sources";
import { ErrorState } from "@/components/states/error-state";
import { StatePanel } from "@/components/states/state-panel";
import { buttonVariants } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { routes } from "@/config/routes";
import {
  type Environment,
  type EnvironmentNode,
  type EnvironmentStatus,
} from "@/lib/environment";
import { useEnvironment } from "@/lib/environment-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { isConnected } from "@/lib/sources";
import { useSources } from "@/lib/sources-queries";

/**
 * "Mon environnement", laid out as docs/product/mockups/10-mon-environnement-
 * cartographie.jpeg (LEKA-359).
 *
 * Every block of the mockup is here, in its place, and every figure is real:
 * what entity resolution and enrichment made of the connected sources. What
 * no source says yet — the users, the business domains, LEKA's insights —
 * the block says so in its own words, as the overview does, rather than
 * showing the mockup's numbers.
 */

const TABS = ["company", "domains", "applications", "services", "infrastructure"] as const;
type Tab = (typeof TABS)[number];

const ROWS: Record<Tab, readonly Layer[]> = {
  company: LAYERS,
  domains: [],
  applications: ["applications"],
  services: ["services"],
  infrastructure: ["data", "infrastructure"],
};

const LEGEND = ["operational", "attention", "incident", "unmonitored"] as const;
const LEGEND_TONE = {
  operational: "success",
  attention: "warning",
  incident: "danger",
  unmonitored: "neutral",
} as const;

const GLOBAL = "global";
const SOURCE_ROWS = 5;

export function EnvironmentScreen() {
  const t = useDictionary();
  const w = t.environment;
  const environment = useEnvironment();
  const [tab, setTab] = useState<Tab>("company");
  const [view, setView] = useState<"map" | "list">("map");
  const [scope, setScope] = useState(GLOBAL);
  const [detailed, setDetailed] = useState(false);

  const data = environment.data;
  const nodes = useMemo(() => {
    const all = data?.nodes ?? [];
    return scope === GLOBAL
      ? all
      : all.filter((node) => !node.environment || node.environment === scope);
  }, [data, scope]);

  return (
    <PageContainer>
      <Header data={data} view={view} onView={setView} scope={scope} onScope={setScope} />

      <div className="mb-4 flex flex-col gap-3 rounded-xl border border-shell-line bg-white p-2 lg:flex-row lg:items-center">
        <div role="group" aria-label={w.tabsLabel} className="flex flex-wrap gap-1.5">
          {TABS.map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={tab === key}
              onClick={() => setTab(key)}
              data-testid={`env-tab-${key}`}
              className={cn(
                "rounded-lg border px-4 py-1.5 text-sm font-medium outline-none transition-colors focus-visible:ring-3 focus-visible:ring-brand-violet/40",
                tab === key
                  ? "border-brand-violet/30 bg-brand-violet-soft text-shell-nav-active"
                  : "border-shell-line text-brand-navy hover:bg-shell-canvas",
              )}
            >
              {w.tabs[key]}
            </button>
          ))}
        </div>
        <ul aria-label={w.legend} className="flex flex-wrap gap-x-5 gap-y-1 lg:ml-auto lg:pr-2">
          {LEGEND.map((state) => (
            <li key={state} className="flex items-center gap-2 text-[0.8125rem] text-brand-navy">
              <span
                aria-hidden="true"
                className={cn("size-2.5 rounded-full", TONES[LEGEND_TONE[state]].dot)}
              />
              {t.knowledge.status.entity[state]}
            </li>
          ))}
        </ul>
      </div>

      {environment.isError ? (
        <ErrorState error={environment.error} onRetry={() => void environment.refetch()} />
      ) : (
        <>
          <Figures data={data} />
          <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
            <div className="flex min-w-0 flex-col gap-4">
              <MapCard
                data={data}
                nodes={nodes}
                tab={tab}
                view={view}
                detailed={detailed}
                onDetailed={() => setDetailed((current) => !current)}
                onMore={() => setView("list")}
              />
              <div className="grid gap-4 lg:grid-cols-2">
                <Card
                  title={w.events.title}
                  action={<CardLink href={routes.activity()}>{w.kpi.seeAll}</CardLink>}
                >
                  <EventList events={data?.events ?? []} empty={w.events.empty} />
                </Card>
                <Card title={w.attention.title}>
                  <AttentionList points={data?.attention ?? []} empty={w.attention.empty} />
                </Card>
              </div>
            </div>
            <div className="flex flex-col gap-4">
              <Insights />
              <Sources />
              <Help />
            </div>
          </div>
        </>
      )}
    </PageContainer>
  );
}

function Header({
  data,
  view,
  onView,
  scope,
  onScope,
}: {
  data: Environment | undefined;
  view: "map" | "list";
  onView: (view: "map" | "list") => void;
  scope: string;
  onScope: (scope: string) => void;
}) {
  const t = useDictionary();
  const w = t.environment;
  const scopes = [
    { value: GLOBAL, label: w.global },
    ...(data?.environments ?? []).map((name) => ({ value: name, label: name })),
  ];
  return (
    <div className="mb-5 flex flex-col gap-4 xl:flex-row xl:items-end">
      <div className="min-w-0 flex-1">
        <nav aria-label={t.shell.breadcrumb} className="mb-2">
          <ol className="flex items-center gap-2 text-[0.8125rem] text-shell-muted">
            <li className="flex items-center gap-2">
              <Layers className="size-4 text-shell-nav-active" aria-hidden="true" />
              <span aria-current="page">{t.nav.environment}</span>
            </li>
          </ol>
        </nav>
        <h1 className="text-[2rem] leading-tight font-bold tracking-[-0.02em] text-brand-navy">
          {w.title}
        </h1>
        <p className="mt-1 text-[1.0625rem] text-shell-accent-muted">{w.subtitle}</p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <p className="flex items-center gap-2 text-xs text-shell-muted" aria-live="polite">
          <span
            aria-hidden="true"
            className={cn(
              "size-2.5 rounded-full",
              data?.updated_at ? "bg-state-success" : "bg-shell-muted",
            )}
          />
          <span>
            <span className="block">{w.updated}</span>
            <span className="block font-medium text-brand-navy">
              {data?.updated_at ? timeAgo(t, data.updated_at) : w.neverUpdated}
            </span>
          </span>
        </p>
        <Select
          value={scope}
          onValueChange={(value) => onScope((value as string | null) ?? GLOBAL)}
          items={scopes}
        >
          <SelectTrigger className="min-w-40" aria-label={w.scope}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {scopes.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div
          role="group"
          aria-label={w.views}
          className="flex overflow-hidden rounded-lg border border-shell-line"
        >
          {(
            [
              ["map", MapIcon, w.mapView],
              ["list", List, w.listView],
            ] as const
          ).map(([key, Icon, label]) => (
            <button
              key={key}
              type="button"
              aria-pressed={view === key}
              aria-label={label}
              title={label}
              onClick={() => onView(key)}
              className={cn(
                "flex size-10 items-center justify-center outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
                view === key
                  ? "bg-brand-violet-soft text-shell-nav-active"
                  : "bg-white text-brand-navy",
              )}
            >
              <Icon className="size-5" aria-hidden="true" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function Figures({ data }: { data: Environment | undefined }) {
  const t = useDictionary();
  const k = t.environment.kpi;
  const sources = useSources();
  const list = sources.data ?? [];
  const connected = list.filter(isConnected).length;
  const share = list.length ? Math.round((connected / list.length) * 100) : 0;
  const value = (n: number | undefined) => (n === undefined ? "—" : String(n));

  const tiles: {
    icon: typeof CircleCheck;
    tone: TileTone;
    value: string;
    label: string;
    sub: React.ReactNode;
    id: string;
    action?: React.ReactNode;
  }[] = [
    {
      id: "sources",
      icon: Waypoints,
      tone: "violet",
      value: sources.data ? `${connected} / ${list.length}` : "—",
      label: k.sources,
      sub: sources.data ? (
        <span className="flex items-center gap-2">
          <span
            className="h-1.5 flex-1 overflow-hidden rounded-full bg-shell-canvas"
            role="meter"
            aria-label={k.sources}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={share}
          >
            <span
              className="block h-full rounded-full bg-state-success"
              style={{ width: `${share}%` }}
            />
          </span>
          <span>{share} %</span>
        </span>
      ) : null,
    },
    {
      id: "services",
      icon: CircleCheck,
      tone: "success",
      value: value(data?.services_operational),
      label: k.servicesUp,
      sub: data ? fill(k.servicesOf, { count: data.services }) : null,
    },
    {
      id: "attention",
      icon: TriangleAlert,
      tone: "warning",
      value: value(data?.attention.length),
      label: k.attention,
      sub: k.toInvestigate,
    },
    {
      id: "incidents",
      icon: TriangleAlert,
      tone: "danger",
      value: value(data?.incidents_open),
      label: k.incidents,
      sub: data ? fill(k.impacting, { count: data.services_impacted }) : null,
    },
    {
      id: "changes",
      icon: FileClock,
      tone: "info",
      value: value(data?.changes_24h),
      label: k.changes,
      sub: k.since24h,
      action: <CardLink href={routes.activity()}>{k.seeAll}</CardLink>,
    },
  ];

  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      {tiles.map((tile) => (
        <li
          key={tile.id}
          className="rounded-xl border border-shell-line bg-white p-4"
          data-testid={`env-kpi-${tile.id}`}
        >
          <div className="flex items-start gap-3">
            <IconTile icon={tile.icon} tone={tile.tone} />
            <div className="min-w-0 flex-1">
              <p className="text-[1.5rem] leading-7 font-bold text-brand-navy">{tile.value}</p>
              <p className="text-[0.8125rem] leading-4 text-brand-navy">{tile.label}</p>
              {tile.sub ? <div className="mt-1 text-xs text-shell-muted">{tile.sub}</div> : null}
            </div>
            {tile.action}
          </div>
        </li>
      ))}
    </ul>
  );
}

function MapCard({
  data,
  nodes,
  tab,
  view,
  detailed,
  onDetailed,
  onMore,
}: {
  data: Environment | undefined;
  nodes: readonly EnvironmentNode[];
  tab: Tab;
  view: "map" | "list";
  detailed: boolean;
  onDetailed: () => void;
  onMore: () => void;
}) {
  const t = useDictionary();
  const w = t.environment.map;
  const rows = ROWS[tab];
  const empty = data !== undefined && data.nodes.length === 0;

  let body: React.ReactNode;
  if (data === undefined) {
    body = <div className="h-80 animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />;
  } else if (tab === "domains") {
    body = (
      <StatePanel
        icon={Network}
        title={w.domainsTitle}
        description={w.domainsBody}
        size="section"
      />
    );
  } else if (empty) {
    body = (
      <StatePanel
        icon={Network}
        title={w.emptyTitle}
        description={w.emptyBody}
        size="section"
        actions={
          <Link href={routes.sources()} className={buttonVariants({ variant: "outline" })}>
            <Plus className="size-4" aria-hidden="true" />
            {t.overview.addSource}
          </Link>
        }
      />
    );
  } else if (view === "list") {
    body = <NodeList nodes={nodes.filter((node) => rows.includes(node.layer as Layer))} />;
  } else {
    body = (
      <Cartography
        nodes={nodes}
        edges={data.edges}
        layers={data.layers}
        rows={rows}
        all={detailed}
        onMore={onMore}
      />
    );
  }

  return (
    <Card
      title={w.title}
      icon={<IconTile icon={Network} tone="violet" className="size-9" />}
      action={
        view === "map" && !empty && tab !== "domains" && data ? (
          <button
            type="button"
            onClick={onDetailed}
            aria-pressed={detailed}
            className="flex items-center gap-1.5 rounded-lg border border-shell-line px-3 py-1.5 text-[0.8125rem] font-medium text-shell-nav-active outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
          >
            {detailed ? w.compact : w.detailed}
            <ArrowRight className="size-3.5" aria-hidden="true" />
          </button>
        ) : null
      }
    >
      {body}
    </Card>
  );
}

function NodeList({ nodes }: { nodes: readonly EnvironmentNode[] }) {
  const t = useDictionary();
  const w = t.environment;
  const columns: KnowledgeColumn<EnvironmentNode>[] = [
    {
      id: "name",
      header: w.list.name,
      sortValue: (node) => node.name,
      cell: (node) =>
        node.entity_id ? (
          <Link
            href={entityHref({ id: node.entity_id, type: node.type })}
            className="font-medium text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          >
            {node.name}
          </Link>
        ) : (
          <span className="font-medium text-brand-navy">
            {(w.providers as Record<string, string>)[node.name] ?? node.name}
            {node.detail ? ` · ${node.detail}` : ""}
          </span>
        ),
    },
    { id: "type", header: w.list.type, cell: (node) => typeLabel(t, node.type) },
    {
      id: "layer",
      header: w.list.layer,
      cell: (node) => (w.map.layers as Record<string, string>)[node.layer] ?? node.layer,
    },
    {
      id: "status",
      header: w.list.status,
      sortValue: (node) => node.status ?? "",
      cell: (node) =>
        node.status ? (
          <StatusBadge variant={`entity.${node.status as EnvironmentStatus}`} size="sm" />
        ) : (
          <span className="text-xs text-shell-muted">{w.noStatus}</span>
        ),
    },
    { id: "team", header: w.list.team, cell: (node) => node.team?.name ?? "—" },
  ];
  return (
    <KnowledgeTable
      caption={w.list.caption}
      columns={columns}
      rows={[...nodes]}
      rowKey={(node) => node.id}
      empty={{ title: w.list.empty }}
    />
  );
}

function Insights() {
  const t = useDictionary();
  const w = t.environment.insights;
  return (
    <Card title={w.title} icon={<IconTile icon={Lightbulb} tone="violet" className="size-9" />}>
      <p className="text-[0.875rem] leading-snug text-shell-muted">{w.empty}</p>
      <Link
        href={routes.intentionNew()}
        className="mt-4 flex items-center justify-center gap-2 rounded-lg bg-brand-navy px-4 py-2.5 text-sm font-medium text-white outline-none hover:bg-brand-navy/90 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
      >
        {w.action}
        <ArrowRight className="size-4" aria-hidden="true" />
      </Link>
    </Card>
  );
}

function Sources() {
  const t = useDictionary();
  const sources = useSources();
  const list = sources.data ?? [];
  return (
    <Card
      title={t.overview.sourcesTitle}
      action={<CardLink href={routes.sources()}>{t.overview.seeAllSources}</CardLink>}
    >
      {sources.data && list.length === 0 ? (
        <p className="py-4 text-center text-[0.8125rem] text-shell-muted">
          {t.overview.sourcesEmpty}
        </p>
      ) : (
        <ConnectedSources sources={list} max={SOURCE_ROWS} />
      )}
      <Link
        href={routes.sources()}
        className="mt-3 flex items-center justify-center gap-2 rounded-lg border border-shell-line px-4 py-2 text-sm font-medium text-brand-navy outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
      >
        <Plus className="size-4" aria-hidden="true" />
        {t.overview.addSource}
      </Link>
    </Card>
  );
}

function Help() {
  const t = useDictionary();
  const w = t.environment.help;
  return (
    <Link
      href={routes.intentionNew()}
      className="flex items-center gap-4 rounded-xl border border-shell-line bg-shell-highlight p-4 outline-none hover:border-brand-violet/40 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
    >
      <IconTile icon={CircleHelp} tone="violet" />
      <span className="min-w-0 flex-1">
        <span className="block text-[0.9375rem] font-semibold text-brand-navy">{w.title}</span>
        <span className="block text-[0.8125rem] text-shell-muted">{w.body}</span>
      </span>
      <ArrowRight className="size-4 text-shell-nav-active" aria-hidden="true" />
    </Link>
  );
}
