"use client";

import {
  ArrowRight,
  CircleHelp,
  Layers,
  Lightbulb,
  List,
  Map as MapIcon,
  Network,
  Plus,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { cn } from "cn";

import { KnowledgeTable, type KnowledgeColumn } from "@/components/knowledge/knowledge-table";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { timeAgo } from "@/components/knowledge/time";
import { ArchitectureBoard, ArchitectureFigures } from "@/components/environment/architecture";
import { LekaInsights } from "@/components/insights/leka-insights";
import { Cartography } from "@/components/environment/cartography";
import { QualityTab } from "@/components/environment/knowledge-quality";
import { CoveragePanel } from "@/components/environment/coverage";
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
  typeLabel,
} from "@/components/environment/parts";
import { PageContainer } from "@/components/shell/page-container";
import {
  type SourceLine,
  SourceLines,
  sourceLines,
} from "@/components/sources/connected-sources";
import { ErrorState } from "@/components/states/error-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ENVIRONMENT_VIEWS, routes } from "@/config/routes";
import type { Environment, EnvironmentStatus } from "@/lib/environment";
import { useEnvironment, useMonitoring } from "@/lib/environment-queries";
import { type TwinStateName, twinOf, withTwin } from "@/lib/twin";
import {
  AlertsCard,
  FreshnessLine,
  SourcesCoverage,
  TwinCounts,
  TwinLegend,
  TwinList,
} from "@/components/environment/twin";
import type { LandscapeView, ViewName, ViewNode } from "@/lib/knowledge-graph";
import { useArchitecture, useLandscapeView } from "@/lib/knowledge-graph-queries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Source } from "@/lib/sources";
import { useSources } from "@/lib/sources-queries";

/**
 * "Mon environnement" (LEKA-359, redrawn by LEKA-369 after Haitam's
 * mockup): what the company runs and how it is doing.
 *
 * Every figure is the workspace's own — what entity resolution and
 * enrichment made of its sources. Nothing mapped yet, the screen keeps the
 * mockup's structure, and each part says what would fill it. No number is
 * ever invented.
 *
 * The figures above every tab, and the first tab, are the ARCHITECTURE
 * (GET /knowledge/architecture, architecture.tsx): the code, the services,
 * the data, the cloud, what is relied on outside, in columns, their links
 * named. The other tabs are landscapes of the company model (GET
 * /knowledge/views/{view}): their rows, boxes and lines, how well their
 * kinds are known; Événements, what moved. The detailed map explores the
 * graph behind them (graph-explorer.tsx).
 *
 * The tab is in the URL (`?tab=applications`, LEKA-428): the sidebar opens
 * each view of "Mon environnement" by it, and a view can be shared or
 * reloaded. No `tab`, or one that is not a tab, is the architecture.
 */

const TABS = ENVIRONMENT_VIEWS;
type Tab = (typeof TABS)[number];
const FIRST_TAB: Tab = "architecture";

function isTab(value: string | null): value is Tab {
  return (TABS as readonly (string | null)[]).includes(value);
}

/** The tab the URL asks for, and the way to another — replacing the
 * address rather than stacking one per click. */
function useTab(): [Tab, (next: Tab) => void] {
  const router = useRouter();
  const pathname = usePathname() ?? "/environment";
  const search = useSearchParams();
  const asked = search?.get("tab") ?? null;
  const tab = isTab(asked) ? asked : FIRST_TAB;
  function setTab(next: Tab) {
    const params = new URLSearchParams(search?.toString() ?? "");
    if (next === FIRST_TAB) params.delete("tab");
    else params.set("tab", next);
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }
  return [tab, setTab];
}
const VIEWS_OF: Partial<Record<Tab, ViewName>> = {
  applications: "applications",
  infrastructure: "infrastructure",
  data: "data",
  dependencies: "dependencies",
  organisation: "organisation",
  domains: "domains",
};

const GLOBAL = "global";
const SOURCE_ROWS = 5;

/** Everything the screen shows but the map, which is its tab's. */
interface Model {
  updatedAt: string | null;
  environments: string[];
  sources: SourceLine[] | null;
  events: EventRow[];
  attention: AttentionRow[];
}

function useModel(): { model: Model | undefined; error: unknown; retry: () => void } {
  const t = useDictionary();
  const environment = useEnvironment();
  const sources = useSources();

  const model = useMemo((): Model | undefined => {
    const data = environment.data;
    if (!data) return undefined;
    return real(t, data, sources.data);
  }, [environment.data, sources.data, t]);

  return {
    model,
    error: environment.isError ? environment.error : null,
    retry: () => void environment.refetch(),
  };
}

function real(
  t: ReturnType<typeof useDictionary>,
  data: Environment,
  sources: Source[] | undefined,
): Model {
  return {
    updatedAt: data.updated_at,
    environments: data.environments,
    sources: sources ? sourceLines(sources) : null,
    events: eventRows(t, data.events),
    attention: attentionRows(t, data.attention),
  };
}

export function EnvironmentScreen() {
  const t = useDictionary();
  const w = t.environment;
  const { model, error, retry } = useModel();
  const [tab, setTab] = useTab();
  const [view, setView] = useState<"map" | "list">("map");
  const [scope, setScope] = useState(GLOBAL);
  const [only, setOnly] = useState<TwinStateName | null>(null);
  const viewName = VIEWS_OF[tab] ?? null;
  const landscape = useLandscapeView(viewName);
  const architectureRead = useArchitecture(scope === GLOBAL ? null : scope);
  // The Digital Twin (LEKA-442): one state per thing on every view — the
  // map, its list, a sheet.
  const environment = useEnvironment();
  const monitoring = useMonitoring();
  const twin = useMemo(() => twinOf(environment.data), [environment.data]);
  const architecture = {
    ...architectureRead,
    data: useMemo(() => withTwin(architectureRead.data, twin), [architectureRead.data, twin]),
  };

  const nodes = useMemo(() => {
    const all = (landscape.data?.nodes ?? []).map((node) => {
      const found = node.entity_id ? twin.get(node.entity_id) : undefined;
      return found ? { ...node, status: found.state } : node;
    });
    return scope === GLOBAL
      ? all
      : all.filter((node) => !node.environment || node.environment === scope);
  }, [landscape.data, scope, twin]);
  const tracked = useMemo(
    () =>
      (environment.data?.nodes ?? []).filter(
        (node) => scope === GLOBAL || !node.environment || node.environment === scope,
      ),
    [environment.data, scope],
  );
  function pick(state: TwinStateName | null) {
    setOnly(state);
    if (state) setView("list");
  }
  const environments = useMemo(
    () => [
      ...new Set([...(model?.environments ?? []), ...(architecture.data?.environments ?? [])]),
    ],
    [model?.environments, architecture.data?.environments],
  );

  let body: React.ReactNode;
  if (tab === "architecture") {
    body = architecture.isError ? (
      <ErrorState error={architecture.error} onRetry={() => void architecture.refetch()} />
    ) : architecture.data ? (
      <div className="flex flex-col gap-3">
        {/* How many things in each state — each the way to the list of them. */}
        <Card title={t.environment.twin.counts.title}>
          <TwinCounts states={environment.data?.states ?? {}} active={only} onPick={pick} />
        </Card>
        {view === "list" ? (
          // The readable alternative to the map (LEKA-442).
          <Card title={t.environment.twin.list.caption}>
            <TwinList nodes={tracked} filter={only} />
          </Card>
        ) : (
          <ArchitectureBoard data={architecture.data} />
        )}
        <div className="grid gap-4 xl:grid-cols-2">
          <AlertsCard monitoring={monitoring.data} />
          {environment.data ? (
            <SourcesCoverage
              coverage={environment.data.coverage ?? []}
              sources={environment.data.sources ?? []}
            />
          ) : null}
        </div>
        {/* What moved and what needs a look, as the mockup's foot (LEKA-438). */}
        <Recent model={model} />
      </div>
    ) : (
      <div className="h-96 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />
    );
  } else if (tab === "quality") {
    // How far what LEKA knows can be trusted (LEKA-381).
    body = <QualityTab />;
  } else if (tab === "events") {
    body = (
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card
          title={w.events.title}
          action={<CardLink href={routes.activity()}>{w.kpi.seeAll}</CardLink>}
        >
          <EventList rows={model?.events ?? []} empty={w.events.empty} detailed />
        </Card>
        <Card
          title={w.attention.title}
          action={<CardLink href={routes.approvals()}>{w.kpi.seeAll}</CardLink>}
        >
          <AttentionList rows={model?.attention ?? []} empty={w.attention.empty} />
        </Card>
      </div>
    );
  } else {
    body = (
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="flex min-w-0 flex-col gap-4">
          <MapCard
            landscape={landscape.data}
            error={landscape.isError ? landscape.error : null}
            onRetry={() => void landscape.refetch()}
            nodes={nodes}
            view={view}
            onMore={() => setView("list")}
          />
          <Recent model={model} />
        </div>
        <div className="flex flex-col gap-4">
          <Insights />
          <Sources lines={model?.sources ?? null} />
          <Help />
        </div>
      </div>
    );
  }

  return (
    <PageContainer>
      <Header
        model={model}
        freshness={environment.data?.freshness}
        environments={environments}
        view={view}
        onView={viewName || tab === "architecture" ? setView : null}
        scope={scope}
        onScope={setScope}
        tab={tab}
        onTab={setTab}
      />

      <div className="mb-3 flex flex-wrap items-center gap-2 border-b border-shell-line pb-2">
        {tab === "architecture" ? (
          // The architecture says its states under its canvas: here, the way to the detail.
          <div className="ms-auto shrink-0">
            <DetailedLink />
          </div>
        ) : (
          // The six states, each defined (LEKA-442).
          <TwinLegend className="px-2.5" />
        )}
      </div>

      {error ? (
        <ErrorState error={error} onRetry={retry} />
      ) : (
        <div className="flex flex-col gap-3">
          <ArchitectureFigures data={architecture.data} />
          {body}
        </div>
      )}
    </PageContainer>
  );
}

function Recent({ model }: { model: Model | undefined }) {
  const w = useDictionary().environment;
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <Card title={w.events.title} action={<CardLink href={routes.activity()}>{w.kpi.seeAll}</CardLink>}>
        <EventList rows={model?.events ?? []} empty={w.events.empty} />
      </Card>
      <Card title={w.attention.title} action={<CardLink href={routes.approvals()}>{w.kpi.seeAll}</CardLink>}>
        <AttentionList rows={model?.attention ?? []} empty={w.attention.empty} />
      </Card>
    </div>
  );
}

function DetailedLink() {
  const t = useDictionary();
  return (
    <Link
      href={routes.environmentGraph()}
      className="flex items-center gap-1.5 rounded-lg border border-shell-line px-3 py-1 text-[0.8125rem] font-medium whitespace-nowrap text-shell-nav-active outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
    >
      {t.environment.map.detailed}
      <ArrowRight className="rtl:-scale-x-100 size-3.5" aria-hidden="true" />
    </Link>
  );
}

function Header({
  model,
  freshness,
  environments,
  view,
  onView,
  scope,
  onScope,
  tab,
  onTab,
}: {
  model: Model | undefined;
  freshness: Environment["freshness"] | undefined;
  environments: readonly string[];
  view: "map" | "list";
  /** None: the tab has no list to switch to. */
  onView: ((view: "map" | "list") => void) | null;
  scope: string;
  onScope: (scope: string) => void;
  tab: Tab;
  onTab: (tab: Tab) => void;
}) {
  const t = useDictionary();
  const w = t.environment;
  const tabs = TABS.map((key) => ({ value: key, label: w.tabs[key] }));
  const scopes = [
    { value: GLOBAL, label: w.global },
    ...environments.map((name) => ({ value: name, label: name })),
  ];
  return (
    <div className="mb-3 flex flex-col gap-3 xl:flex-row xl:items-end">
      <div className="min-w-0 flex-1">
        <nav aria-label={t.shell.breadcrumb} className="mb-1">
          <ol className="flex items-center gap-2 text-[0.8125rem] text-shell-muted">
            <li className="flex items-center gap-2">
              <Layers className="size-4 text-shell-nav-active" aria-hidden="true" />
              <span aria-current="page">{t.nav.environment}</span>
            </li>
          </ol>
        </nav>
        <h1 className="text-[1.625rem] leading-tight font-bold tracking-[-0.02em] text-brand-navy">
          {w.title}
        </h1>
        <p className="text-[0.9375rem] text-shell-accent-muted">{w.subtitle}</p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        {freshness ? (
          // When it was really read, how often — never « temps réel » (LEKA-442).
          <div aria-live="polite">
            <FreshnessLine freshness={freshness} />
          </div>
        ) : (
          <p className="flex items-center gap-2 text-xs text-shell-muted" aria-live="polite">
            <span
              aria-hidden="true"
              className={cn(
                "size-2.5 rounded-full",
                model?.updatedAt ? "bg-state-success" : "bg-shell-muted",
              )}
            />
            <span>
              <span className="block">{w.updated}</span>
              <span className="block font-medium text-brand-navy">
                {model?.updatedAt ? timeAgo(t, model.updatedAt) : w.neverUpdated}
              </span>
            </span>
          </p>
        )}
        {/* Its views — the overall one, then applications to quality —
            chosen here, top right (2026-10-14: the sidebar keeps only
            Activité under Mon environnement). */}
        <Select value={tab} onValueChange={(value) => onTab(isTab(value as string | null) ? (value as Tab) : FIRST_TAB)} items={tabs}>
          <SelectTrigger className="min-w-44 bg-white" aria-label={w.tabsLabel} data-testid="env-view">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {tabs.map((option) => (
              <SelectItem key={option.value} value={option.value} data-testid={`env-tab-${option.value}`}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
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
        {onView ? (
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
        ) : null}
      </div>
    </div>
  );
}

function MapCard({
  landscape,
  error,
  onRetry,
  nodes,
  view,
  onMore,
}: {
  landscape: LandscapeView | undefined;
  error: unknown;
  onRetry: () => void;
  nodes: readonly ViewNode[];
  view: "map" | "list";
  onMore: () => void;
}) {
  const t = useDictionary();
  const w = t.environment.map;

  let body: React.ReactNode;
  if (error) {
    body = <ErrorState error={error} onRetry={onRetry} />;
  } else if (landscape === undefined) {
    body = <div className="h-80 animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />;
  } else if (view === "list") {
    body = <NodeList nodes={nodes} />;
  } else {
    body = (
      <Cartography
        nodes={nodes}
        edges={landscape.edges}
        rows={landscape.layers}
        view={landscape.view}
        onMore={onMore}
      />
    );
  }

  return (
    <Card
      title={w.title}
      icon={<IconTile icon={Network} tone="violet" className="size-9" />}
      action={
        <Link
          href={routes.environmentGraph()}
          className="flex items-center gap-1.5 rounded-lg border border-shell-line px-3 py-1.5 text-[0.8125rem] font-medium text-shell-nav-active outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        >
          {w.detailed}
          <ArrowRight className="rtl:-scale-x-100 size-3.5" aria-hidden="true" />
        </Link>
      }
    >
      {body}
      {landscape ? (
        <CoveragePanel coverage={landscape.coverage} sources={landscape.sources} />
      ) : null}
    </Card>
  );
}

function NodeList({ nodes }: { nodes: readonly ViewNode[] }) {
  const t = useDictionary();
  const w = t.environment;
  const columns: KnowledgeColumn<ViewNode>[] = [
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
  return (
    <Card
      title={t.environment.insights.title}
      icon={<IconTile icon={Lightbulb} tone="violet" className="size-9" />}
    >
      {/* What LEKA's analyses concluded (LEKA-377). */}
      <LekaInsights />
    </Card>
  );
}

function Sources({ lines }: { lines: SourceLine[] | null }) {
  const t = useDictionary();
  return (
    <Card
      title={t.overview.sourcesTitle}
      action={<CardLink href={routes.sources()}>{t.overview.seeAllSources}</CardLink>}
    >
      {lines && lines.length === 0 ? (
        <p className="py-4 text-center text-[0.8125rem] text-shell-muted">
          {t.overview.sourcesEmpty}
        </p>
      ) : (
        <SourceLines lines={lines ?? []} max={SOURCE_ROWS} />
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
      <ArrowRight className="rtl:-scale-x-100 size-4 text-shell-nav-active" aria-hidden="true" />
    </Link>
  );
}
