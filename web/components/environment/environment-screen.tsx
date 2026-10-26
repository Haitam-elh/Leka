"use client";

import {
  ArrowLeft,
  ArrowRight,
  CircleHelp,
  Lightbulb,
  List,
  Map as MapIcon,
  Maximize2,
  Network,
  Plus,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { useIsFetching, useQueryClient } from "@tanstack/react-query";

import { cn } from "cn";

import { KnowledgeTable, type KnowledgeColumn } from "@/components/knowledge/knowledge-table";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { timeAgo } from "@/components/knowledge/time";
import { AlertRuleProvider, AlertRulesCard, CreateAlertButton } from "@/components/environment/alert-rules";
import { ArchitectureBoard, ArchitectureFigures } from "@/components/environment/architecture";
import { LekaInsights } from "@/components/insights/leka-insights";
import { Cartography } from "@/components/environment/cartography";
import { QualityTab } from "@/components/environment/knowledge-quality";
import { CoveragePanel } from "@/components/environment/coverage";
import { EntityPicker } from "@/components/environment/entity-picker";
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
import { SourceLocked, useSourceLock } from "@/components/sources/source-lock";
import { usePermissions } from "@/components/shell/shell-provider";
import { AddSourceDialog } from "@/components/sources/add-source-dialog";
import { SourcesPage } from "@/components/sources/sources-page";
import {
  type SourceLine,
  SourceLines,
  sourceLines,
} from "@/components/sources/connected-sources";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTab } from "@/components/ui/tabs";
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
import { overallOf, type TwinStateName, twinOf, withTwin } from "@/lib/twin";
import {
  AlertsCard,
  FreshnessLine,
  ScoreExplained,
  SourcesCoverage,
  TwinCounts,
  TwinLegend,
  TwinList,
} from "@/components/environment/twin";
import type { LandscapeView, ViewName, ViewNode } from "@/lib/knowledge-graph";
import { useArchitecture, useLandscapeView } from "@/lib/knowledge-graph-queries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
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

/** « Mon environnement », locked under a contract until a source is
 * connected (2026-10-25): with nothing read, there is nothing to show. */
export function EnvironmentPage() {
  const t = useDictionary();
  const w = t.environment;
  if (useSourceLock()) {
    return (
      <PageContainer>
        <div className="mb-6 flex flex-col gap-3">
          <Link
            href={routes.overview()}
            className="flex w-fit items-center gap-2 rounded-lg bg-shell-canvas px-3 py-1.5 text-[0.8125rem] font-medium text-brand-navy outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
          >
            <ArrowLeft className="rtl:-scale-x-100 size-4" aria-hidden="true" />
            {w.back}
          </Link>
          <div>
            <h1 className="text-[1.875rem] leading-tight font-bold tracking-[-0.02em] text-brand-navy">
              {w.title}
            </h1>
            <p className="mt-1 text-[0.9375rem] text-shell-accent-muted">{w.subtitle}</p>
          </div>
        </div>
        <SourceLocked what="environment" />
      </PageContainer>
    );
  }
  return <EnvironmentScreen />;
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
        {view === "list" ? (
          // The readable alternative to the map (LEKA-442).
          <Card title={t.environment.twin.list.caption}>
            <TwinList nodes={tracked} filter={only} />
          </Card>
        ) : (
          <ArchitectureBoard data={architecture.data} />
        )}
        {/* The mockup's foot (LEKA-459): the overall state — each state the
            way to the list of its things —, the sources, the alerts, what
            changed. */}
        <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-4">
          <Overall
            states={environment.data?.states ?? {}}
            lastRead={environment.data?.freshness?.last_read_at ?? null}
            active={only}
            onPick={pick}
          />
          <Sources lines={model?.sources ?? null} />
          <AlertsCard monitoring={monitoring.data} />
          <Card
            title={w.events.title}
            action={<CardLink href={routes.activity()}>{w.kpi.seeAll}</CardLink>}
          >
            <EventList rows={model?.events ?? []} empty={w.events.empty} />
          </Card>
        </div>
      </div>
    ) : (
      <div className="h-96 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />
    );
  } else if (tab === "quality") {
    // How far what LEKA knows can be trusted (LEKA-381).
    body = <QualityTab />;
  } else if (tab === "sources") {
    // The sources, moved here from their own page, which stays (LEKA-459).
    body = <SourcesPage embedded />;
  } else if (tab === "configuration") {
    // What sets what this screen shows — never a setting it does not have:
    // the alerts are the common service's (LEKA-463), their rules the
    // person's (LEKA-477).
    body = (
      <div className="grid gap-4 xl:grid-cols-2">
        <Card
          title={w.configuration.sync}
          action={<CardLink href={routes.sources()}>{w.kpi.seeAll}</CardLink>}
        >
          <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.configuration.syncBody}</p>
          {environment.data?.freshness ? <FreshnessLine freshness={environment.data.freshness} /> : null}
          <div className="mt-3">
            <SourceLines lines={model?.sources ?? []} max={50} />
          </div>
        </Card>
        <div className="flex flex-col gap-4">
          <AlertsCard monitoring={monitoring.data} />
          <AlertRulesCard />
          {environment.data ? (
            <SourcesCoverage
              coverage={environment.data.coverage ?? []}
              sources={environment.data.sources ?? []}
            />
          ) : null}
        </div>
      </div>
    );
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
      <AlertRuleProvider>
      <Header model={model} freshness={environment.data?.freshness} />

      {error ? (
        <ErrorState error={error} onRetry={retry} />
      ) : (
        <div className="flex flex-col gap-4">
          <ArchitectureFigures data={architecture.data} />
          <ViewBar
            tab={tab}
            onTab={setTab}
            environments={environments}
            scope={scope}
            onScope={setScope}
            view={view}
            onView={viewName || tab === "architecture" ? setView : null}
          />
          {tab !== "architecture" && viewName ? <TwinLegend className="px-2.5" /> : null}
          {body}
        </div>
      )}
      </AlertRuleProvider>
    </PageContainer>
  );
}

/** The overall state (LEKA-459): the share of what is tracked that is
 * operational, and each state counted — each the way to its list. */
function Overall({
  states,
  lastRead,
  active,
  onPick,
}: {
  states: Readonly<Record<string, number>>;
  lastRead: string | null;
  active: TwinStateName | null;
  onPick: (state: TwinStateName | null) => void;
}) {
  const t = useDictionary();
  const w = t.environment.overall;
  const { format: locale } = useLocale();
  // The overview's « Mon environnement » reads the same rule (LEKA-468).
  const { total, operational, share: counted } = overallOf({ states });
  const share = counted ?? 0;
  return (
    <Card title={w.title}>
      <div className="flex flex-wrap items-center gap-4" data-testid="overall">
        {total ? (
          <div className="relative size-24 shrink-0">
            <svg viewBox="0 0 36 36" className="size-24 -rotate-90" aria-hidden="true">
              <circle cx="18" cy="18" r="15.5" fill="none" strokeWidth="4" className="stroke-shell-canvas" />
              <circle
                cx="18"
                cy="18"
                r="15.5"
                fill="none"
                strokeWidth="4"
                strokeLinecap="round"
                pathLength={100}
                strokeDasharray={`${share * 100} 100`}
                className="stroke-state-success"
              />
            </svg>
            <span className="absolute inset-0 flex flex-col items-center justify-center text-center">
              <span className="text-lg font-bold text-brand-navy" data-testid="overall-share">
                {new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(share)}
              </span>
              <span className="text-[0.6875rem] text-shell-muted">{w.operational}</span>
            </span>
          </div>
        ) : null}
        <div className="min-w-0 flex-1">
          {total ? <TwinCounts states={states} active={active} onPick={onPick} column /> : <p className="text-[0.8125rem] text-shell-muted">{w.empty}</p>}
        </div>
      </div>
      {total ? (
        <ScoreExplained states={states} total={total} operational={operational} lastRead={lastRead} />
      ) : null}
    </Card>
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

function Header({
  model,
  freshness,
}: {
  model: Model | undefined;
  freshness: Environment["freshness"] | undefined;
}) {
  const t = useDictionary();
  const w = t.environment;
  const router = useRouter();
  const client = useQueryClient();
  const fetching = useIsFetching() > 0;
  const canConnect = usePermissions()?.includes("source:manage") ?? false;
  const [connecting, setConnecting] = useState(false);
  return (
    <div className="mb-4 flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link
          href={routes.overview()}
          className="flex items-center gap-2 rounded-lg bg-shell-canvas px-3 py-1.5 text-[0.8125rem] font-medium text-brand-navy outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        >
          <ArrowLeft className="rtl:-scale-x-100 size-4" aria-hidden="true" />
          {w.back}
        </Link>
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
                {w.updated}{" "}
                <span className="font-medium text-brand-navy">
                  {model?.updatedAt ? timeAgo(t, model.updatedAt) : w.neverUpdated}
                </span>
              </span>
            </p>
          )}
          {/* What LEKA knows, read again — the sources are read at their own pace. */}
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={w.refresh}
            title={w.refresh}
            disabled={fetching}
            onClick={() => void client.invalidateQueries()}
            data-testid="env-refresh"
          >
            <RefreshCw className={cn(fetching && "animate-spin motion-reduce:animate-none")} aria-hidden="true" />
          </Button>
          <CreateAlertButton />
          {canConnect ? (
            <Button type="button" onClick={() => setConnecting(true)} data-testid="env-connect">
              <Plus aria-hidden="true" />
              {w.connect}
            </Button>
          ) : null}
        </div>
      </div>
      <div>
        <h1 className="text-[1.875rem] leading-tight font-bold tracking-[-0.02em] text-brand-navy">
          {w.title}
        </h1>
        <p className="mt-1 text-[0.9375rem] text-shell-accent-muted">{w.subtitle}</p>
      </div>
      <AddSourceDialog
        open={connecting}
        onOpenChange={setConnecting}
        onDone={(done) => router.push(`${routes.sources()}?source=${done.id}`)}
      />
    </div>
  );
}

/** The mockup's views, as tabs; the others, in a menu after them. */
const MAIN_TABS = [
  "architecture",
  "applications",
  "dependencies",
  "sources",
  "organisation",
  "events",
  "configuration",
] as const satisfies readonly Tab[];
const MORE_TABS = TABS.filter((key) => !(MAIN_TABS as readonly Tab[]).includes(key));

function ViewBar({
  tab,
  onTab,
  environments,
  scope,
  onScope,
  view,
  onView,
}: {
  tab: Tab;
  onTab: (tab: Tab) => void;
  environments: readonly string[];
  scope: string;
  onScope: (scope: string) => void;
  view: "map" | "list";
  /** None: the tab has no list to switch to. */
  onView: ((view: "map" | "list") => void) | null;
}) {
  const t = useDictionary();
  const w = t.environment;
  const router = useRouter();
  const main = (MAIN_TABS as readonly Tab[]).includes(tab);
  const more = MORE_TABS.map((key) => ({ value: key, label: w.tabs[key] }));
  const scopes = [
    { value: GLOBAL, label: w.global },
    ...environments.map((name) => ({ value: name, label: name })),
  ];
  return (
    <div className="flex flex-col gap-3 border-b border-shell-line xl:flex-row xl:items-end">
      <div className="flex min-w-0 flex-1 items-end gap-2 overflow-x-auto">
        <Tabs value={main ? tab : null} onValueChange={(value) => onTab(value as Tab)} className="gap-0">
          <TabsList aria-label={w.tabsLabel} className="gap-1 rounded-none bg-transparent p-0">
            {MAIN_TABS.map((key) => (
              <TabsTab
                key={key}
                value={key}
                data-testid={`env-tab-${key}`}
                className="h-10 flex-none rounded-none border-b-2 border-transparent px-3 text-[0.9375rem] font-medium text-shell-muted hover:text-brand-navy data-[active]:border-shell-nav-active data-[active]:bg-transparent data-[active]:text-shell-nav-active data-[active]:shadow-none"
              >
                {w.tabs[key]}
              </TabsTab>
            ))}
          </TabsList>
        </Tabs>
        <div className="mb-1.5 shrink-0">
          <Select
            value={main ? null : tab}
            onValueChange={(value) => isTab(value as string | null) && onTab(value as Tab)}
            items={more}
          >
            <SelectTrigger
              className={cn("h-8 min-w-32", !main && "border-brand-violet/60 bg-brand-violet-soft")}
              aria-label={w.more}
              data-testid="env-more"
            >
              <SelectValue placeholder={w.more} />
            </SelectTrigger>
            <SelectContent>
              {more.map((option) => (
                <SelectItem key={option.value} value={option.value} data-testid={`env-tab-${option.value}`}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 pb-2">
        <div className="w-full sm:w-72">
          <EntityPicker
            label={w.search}
            placeholder={w.searchPlaceholder}
            hideLabel
            onPick={(hit) => router.push(entityHref(hit.entity))}
            testId="env-search"
          />
        </div>
        <Select
          value={scope}
          onValueChange={(value) => onScope((value as string | null) ?? GLOBAL)}
          items={scopes}
        >
          <SelectTrigger className="min-w-44" aria-label={w.scope}>
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
                  "flex size-9 items-center justify-center outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
                  view === key
                    ? "bg-brand-violet-soft text-shell-nav-active"
                    : "bg-white text-brand-navy",
                )}
              >
                <Icon className="size-5" aria-hidden="true" />
              </button>
            ))}
            <Link
              href={routes.environmentGraph()}
              aria-label={w.map.detailed}
              title={w.map.detailed}
              className="flex size-9 items-center justify-center border-s border-shell-line bg-white text-brand-navy outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
            >
              <Maximize2 className="size-4" aria-hidden="true" />
            </Link>
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
    { id: "team", header: w.list.team, cell: (node) => node.team?.name ?? "-" },
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
  const canConnect = usePermissions()?.includes("source:manage") ?? false;
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
      {/* Offered to whoever may connect one, as the page's header does. */}
      {canConnect ? (
        <Link
          href={routes.sources()}
          className="mt-3 flex items-center justify-center gap-2 rounded-lg border border-shell-line px-4 py-2 text-sm font-medium text-brand-navy outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        >
          <Plus className="size-4" aria-hidden="true" />
          {t.overview.addSource}
        </Link>
      ) : null}
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
