"use client";

import {
  ArrowRight,
  ChevronRight,
  CircleHelp,
  Layers,
  Lightbulb,
  List,
  type LucideIcon,
  Map as MapIcon,
  Network,
  Plus,
} from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { cn } from "cn";

import { KnowledgeTable, type KnowledgeColumn } from "@/components/knowledge/knowledge-table";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { TONES } from "@/components/knowledge/status";
import { timeAgo } from "@/components/knowledge/time";
import { ArchitectureBoard, ArchitectureFigures } from "@/components/environment/architecture";
import { Cartography } from "@/components/environment/cartography";
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
  type TileTone,
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
import { routes } from "@/config/routes";
import type { Environment, EnvironmentStatus } from "@/lib/environment";
import { useEnvironment } from "@/lib/environment-queries";
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
 */

const TABS = [
  "architecture",
  "applications",
  "infrastructure",
  "data",
  "dependencies",
  "organisation",
  "events",
  "domains",
] as const;
type Tab = (typeof TABS)[number];
const VIEWS_OF: Partial<Record<Tab, ViewName>> = {
  applications: "applications",
  infrastructure: "infrastructure",
  data: "data",
  dependencies: "dependencies",
  organisation: "organisation",
  domains: "domains",
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

interface Insight {
  key: string;
  icon: LucideIcon;
  tone: TileTone;
  title: string;
  detail: string;
}

/** Everything the screen shows but the map, which is its tab's. */
interface Model {
  updatedAt: string | null;
  environments: string[];
  insights: Insight[];
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
    insights: [],
    sources: sources ? sourceLines(sources) : null,
    events: eventRows(t, data.events),
    attention: attentionRows(t, data.attention),
  };
}

export function EnvironmentScreen() {
  const t = useDictionary();
  const w = t.environment;
  const { model, error, retry } = useModel();
  const [tab, setTab] = useState<Tab>("architecture");
  const [view, setView] = useState<"map" | "list">("map");
  const [scope, setScope] = useState(GLOBAL);
  const viewName = VIEWS_OF[tab] ?? null;
  const landscape = useLandscapeView(viewName);
  const architecture = useArchitecture(scope === GLOBAL ? null : scope);

  const nodes = useMemo(() => {
    const all = landscape.data?.nodes ?? [];
    return scope === GLOBAL
      ? all
      : all.filter((node) => !node.environment || node.environment === scope);
  }, [landscape.data, scope]);
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
      <ArchitectureBoard data={architecture.data} events={model?.events ?? []} />
    ) : (
      <div className="h-96 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />
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
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
            <Card
              title={w.events.title}
              action={<CardLink href={routes.activity()}>{w.kpi.seeAll}</CardLink>}
            >
              <EventList rows={model?.events ?? []} empty={w.events.empty} />
            </Card>
            <Card
              title={w.attention.title}
              action={<CardLink href={routes.approvals()}>{w.kpi.seeAll}</CardLink>}
            >
              <AttentionList rows={model?.attention ?? []} empty={w.attention.empty} />
            </Card>
          </div>
        </div>
        <div className="flex flex-col gap-4">
          <Insights insights={model?.insights ?? []} />
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
        environments={environments}
        view={view}
        onView={viewName ? setView : null}
        scope={scope}
        onScope={setScope}
      />

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

      {error ? (
        <ErrorState error={error} onRetry={retry} />
      ) : (
        <div className="flex flex-col gap-4">
          <ArchitectureFigures data={architecture.data} />
          {tab === "architecture" ? (
            <div className="flex justify-end">
              <DetailedLink />
            </div>
          ) : null}
          {body}
        </div>
      )}
    </PageContainer>
  );
}

function DetailedLink() {
  const t = useDictionary();
  return (
    <Link
      href={routes.environmentGraph()}
      className="flex items-center gap-1.5 rounded-lg border border-shell-line bg-white px-3 py-1.5 text-[0.8125rem] font-medium text-shell-nav-active outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
    >
      {t.environment.map.detailed}
      <ArrowRight className="size-3.5" aria-hidden="true" />
    </Link>
  );
}

function Header({
  model,
  environments,
  view,
  onView,
  scope,
  onScope,
}: {
  model: Model | undefined;
  environments: readonly string[];
  view: "map" | "list";
  /** None: the tab has no list to switch to. */
  onView: ((view: "map" | "list") => void) | null;
  scope: string;
  onScope: (scope: string) => void;
}) {
  const t = useDictionary();
  const w = t.environment;
  const scopes = [
    { value: GLOBAL, label: w.global },
    ...environments.map((name) => ({ value: name, label: name })),
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
          <ArrowRight className="size-3.5" aria-hidden="true" />
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

function Insights({ insights }: { insights: readonly Insight[] }) {
  const t = useDictionary();
  const w = t.environment.insights;
  return (
    <Card
      title={w.title}
      icon={<IconTile icon={Lightbulb} tone="violet" className="size-9" />}
      action={
        insights.length ? (
          <CardLink href={routes.intentions()}>{t.environment.kpi.seeAll}</CardLink>
        ) : null
      }
    >
      {insights.length ? (
        <ul className="divide-y divide-shell-line/60">
          {insights.map((insight) => (
            <li key={insight.key} className="flex items-start gap-3 py-2.5">
              <IconTile icon={insight.icon} tone={insight.tone} className="size-9" />
              <span className="min-w-0 flex-1">
                <span className="block text-[0.8125rem] font-semibold text-brand-navy">
                  {insight.title}
                </span>
                <span className="block text-xs text-shell-muted">{insight.detail}</span>
              </span>
              <ChevronRight className="mt-2 size-4 text-shell-muted" aria-hidden="true" />
            </li>
          ))}
        </ul>
      ) : (
        <>
          <p className="text-[0.875rem] leading-snug text-shell-muted">{w.empty}</p>
          <Link
            href={routes.intentionNew()}
            className="mt-4 flex items-center justify-center gap-2 rounded-lg bg-brand-navy px-4 py-2.5 text-sm font-medium text-white outline-none hover:bg-brand-navy/90 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
          >
            {w.action}
            <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
        </>
      )}
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
      <ArrowRight className="size-4 text-shell-nav-active" aria-hidden="true" />
    </Link>
  );
}
