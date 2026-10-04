"use client";

import { ArrowLeft, ArrowRight, Crosshair, Network, Route } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { ArchitectureDossier } from "@/components/environment/architecture-dossier";
import { EntityPicker } from "@/components/environment/entity-picker";
import { Card, entityHref, IconTile, typeIcon, typeLabel } from "@/components/environment/parts";
import { DependencyGraph, layered, rowPositions } from "@/components/knowledge/dependency-graph";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { ErrorState } from "@/components/states/error-state";
import { StatePanel } from "@/components/states/state-panel";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { routes } from "@/config/routes";
import { isEntityId } from "@/lib/environment";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type {
  EntityStatus,
  EntityType,
  KnowledgeEntity,
  KnowledgeRelationship,
  RelationshipType,
} from "@/lib/knowledge";
import {
  type Direction,
  type EntityBrief,
  RELATION_FAMILIES,
  type RelationFamily,
} from "@/lib/knowledge-graph";
import { useArchitecture, useGraphPaths, useGraphWalk } from "@/lib/knowledge-graph-queries";

const DEPTHS = ["1", "2", "3"] as const;
const DIRECTIONS: readonly Direction[] = ["both", "outgoing", "incoming"];
const FAMILIES = Object.keys(RELATION_FAMILIES) as RelationFamily[];
const STATUSES = new Set(["operational", "attention", "incident", "unmonitored"]);

/** What the canvas draws, whichever question it answers. */
interface Drawn {
  entities: KnowledgeEntity[];
  relationships: KnowledgeRelationship[];
  positions: Record<string, { x: number; y: number }>;
  /** Each entity's distance from the root, on a walk. */
  depth: Map<string, number>;
  sources: Map<string, readonly string[]>;
  truncated: boolean;
}

function entity(brief: { id: string; type: string; name: string }, status?: string | null) {
  return {
    id: brief.id,
    type: brief.type as EntityType,
    name: brief.name,
    status: status && STATUSES.has(status) ? (status as EntityStatus) : undefined,
  } satisfies KnowledgeEntity;
}

/**
 * "Voir la cartographie détaillée" (LEKA-369): the company's graph,
 * explored. With nothing chosen, the whole architecture — every card's own
 * arrows, each named (architecture.tsx); a database's tables only once it
 * is chosen. With a thing chosen (?entity=),
 * what surrounds it, 1 to 3 steps away, one way or both, through the
 * relationships asked — the canvas re-centred on whatever is picked — and
 * the shortest ways from it to anything else.
 *
 * Every box and line is the API's (api/leka/api/graph.py); the canvas is
 * also written out as lists for screen readers (DependencyGraph).
 */
export function GraphExplorer() {
  const t = useDictionary();
  const w = t.environment.explorer;
  const router = useRouter();
  const searched = useSearchParams().get("entity");
  const root = searched && isEntityId(searched) ? searched : null;
  const [depth, setDepth] = useState<(typeof DEPTHS)[number]>("1");
  const [direction, setDirection] = useState<Direction>("both");
  const [family, setFamily] = useState<RelationFamily>("all");
  const [selected, setSelected] = useState<string | null>(null);
  const [target, setTarget] = useState<EntityBrief | null>(null);

  const walk = useGraphWalk(
    root
      ? {
          root,
          depth: Number(depth),
          direction,
          relationships: RELATION_FAMILIES[family] as readonly RelationshipType[],
        }
      : null,
  );
  const architecture = useArchitecture(null, root === null, true);
  const query = root ? walk : architecture;

  const drawn = useMemo((): Drawn | undefined => {
    if (root) {
      const data = walk.data;
      if (!data) return undefined;
      const byDepth = new Map<number, KnowledgeEntity[]>();
      for (const node of data.nodes) {
        byDepth.set(node.depth, [...(byDepth.get(node.depth) ?? []), entity(node.entity)]);
      }
      const relationships = data.relationships.map((link) => ({
        id: link.id,
        from: link.from_entity_id,
        to: link.to_entity_id,
        type: link.type as RelationshipType,
        confidence: link.confidence,
      }));
      // Each distance its rows, what points to what going down.
      const rows = layered(
        [...byDepth.keys()].sort((a, b) => a - b).map((d) => byDepth.get(d) ?? []),
        relationships,
      );
      return {
        entities: rows.flat(),
        relationships,
        positions: rowPositions(rows),
        depth: new Map(data.nodes.map((node) => [node.entity.id, node.depth])),
        sources: new Map(data.nodes.map((node) => [node.entity.id, node.sources])),
        truncated: data.truncated,
      };
    }
    return undefined;
  }, [root, walk.data]);

  function centre(id: string) {
    setSelected(null);
    setTarget(null);
    router.replace(routes.environmentGraph(id));
  }

  const rootBrief = root ? walk.data?.roots[0] : undefined;
  const focused = drawn?.entities.find((one) => one.id === (selected ?? root ?? ""));

  return (
    <PageContainer>
      <PageHeader
        title={w.title}
        subtitle={w.subtitle}
        breadcrumb={[
          { label: t.nav.environment, href: routes.environment() },
          ...(rootBrief
            ? [
                { label: w.title, href: routes.environmentGraph() },
                { label: rootBrief.name },
              ]
            : [{ label: w.title }]),
        ]}
      />

      <div className="mb-4 flex flex-col gap-3 rounded-xl border border-shell-line bg-white p-3 lg:flex-row lg:items-end">
        <EntityPicker
          label={w.focus}
          placeholder={w.focusPlaceholder}
          onPick={(hit) => centre(hit.entity.id)}
          testId="explorer-focus"
        />
        {root ? (
          <>
            <Choice
              label={w.depth}
              value={depth}
              onChange={(value) => setDepth(value as (typeof DEPTHS)[number])}
              options={DEPTHS.map((value) => ({ value, label: w.depths[value] }))}
            />
            <Choice
              label={w.direction}
              value={direction}
              onChange={(value) => setDirection(value as Direction)}
              options={DIRECTIONS.map((value) => ({ value, label: w.directions[value] }))}
            />
            <Choice
              label={w.relations}
              value={family}
              onChange={(value) => setFamily(value as RelationFamily)}
              options={FAMILIES.map((value) => ({ value, label: w.families[value] }))}
            />
            <Link
              href={routes.environmentGraph()}
              className="flex h-9 items-center gap-1.5 rounded-lg border border-shell-line px-3 text-[0.8125rem] font-medium text-brand-navy outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
            >
              <ArrowLeft className="size-4" aria-hidden="true" />
              {w.reset}
            </Link>
          </>
        ) : null}
      </div>

      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : !root ? (
        architecture.data ? (
          <ArchitectureDossier data={architecture.data} />
        ) : (
          <div className="h-[560px] animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />
        )
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <Card
            title={rootBrief?.name ?? w.title}
            icon={<IconTile icon={Network} tone="violet" className="size-9" />}
          >
            {drawn === undefined ? (
              <div className="h-[560px] animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />
            ) : drawn.entities.length === 0 ? (
              <StatePanel
                icon={Network}
                size="section"
                headingLevel={3}
                title={w.emptyTitle}
                description={w.emptyBody}
              />
            ) : drawn.entities.length === 1 && root ? (
              <StatePanel
                icon={Network}
                size="section"
                headingLevel={3}
                title={w.aloneTitle}
                description={w.aloneBody}
              />
            ) : (
              <>
                <p className="mb-2 text-xs text-shell-muted" data-testid="explorer-counts">
                  {fill(w.counts, {
                    entities: drawn.entities.length,
                    relationships: drawn.relationships.length,
                  })}
                </p>
                {drawn.truncated ? (
                  <p className="mb-2 text-xs text-state-warning" role="status">
                    {w.truncated}
                  </p>
                ) : null}
                <DependencyGraph
                  // A new question, a new canvas: fitted to what it answers.
                  key={root}
                  entities={drawn.entities}
                  relationships={drawn.relationships}
                  positions={drawn.positions}
                  selectedId={selected ?? root ?? undefined}
                  onNodeClick={setSelected}
                  height={560}
                />
              </>
            )}
          </Card>

          <div className="flex flex-col gap-4">
            <Selected
              entity={focused}
              isRoot={focused?.id === root}
              depth={focused ? drawn?.depth.get(focused.id) : undefined}
              sources={focused ? (drawn?.sources.get(focused.id) ?? []) : []}
              onCentre={centre}
            />
            {root && rootBrief ? (
              <PathFinder root={rootBrief} target={target} onTarget={setTarget} />
            ) : null}
          </div>
        </div>
      )}
    </PageContainer>
  );
}

function Choice({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly { value: string; label: string }[];
}) {
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-shell-muted">{label}</p>
      <Select
        value={value}
        onValueChange={(next) => onChange((next as string | null) ?? value)}
        items={options}
      >
        <SelectTrigger className="h-9 min-w-36" aria-label={label}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function Selected({
  entity: chosen,
  isRoot,
  depth,
  sources,
  onCentre,
}: {
  entity: KnowledgeEntity | undefined;
  isRoot: boolean;
  depth: number | undefined;
  sources: readonly string[];
  onCentre: (id: string) => void;
}) {
  const t = useDictionary();
  const w = t.environment.explorer;
  if (!chosen) return null;
  const Icon = typeIcon(chosen.type);
  return (
    <Card title={chosen.name} icon={<IconTile icon={Icon} tone="violet" className="size-9" />}>
      <dl className="space-y-1.5 text-[0.8125rem]" data-testid="explorer-selected">
        <div className="flex justify-between gap-3">
          <dt className="text-shell-muted">{t.environment.list.type}</dt>
          <dd className="text-brand-navy">{typeLabel(t, chosen.type)}</dd>
        </div>
        {depth !== undefined ? (
          <div className="flex justify-between gap-3">
            <dt className="text-shell-muted">{w.depth}</dt>
            <dd className="text-brand-navy">
              {isRoot ? w.root : fill(w.distance, { count: depth })}
            </dd>
          </div>
        ) : null}
        {sources.length ? (
          <div className="flex justify-between gap-3">
            <dt className="text-shell-muted">{w.shownBy}</dt>
            <dd className="text-right text-brand-navy">{sources.join(", ")}</dd>
          </div>
        ) : null}
      </dl>
      <div className="mt-4 flex flex-wrap gap-2">
        <Link
          href={entityHref({ id: chosen.id, type: chosen.type })}
          className="flex items-center gap-1.5 rounded-lg bg-brand-navy px-3 py-1.5 text-[0.8125rem] font-medium text-white outline-none hover:bg-brand-navy/90 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        >
          {w.open}
          <ArrowRight className="size-3.5" aria-hidden="true" />
        </Link>
        {!isRoot ? (
          <button
            type="button"
            onClick={() => onCentre(chosen.id)}
            className="flex items-center gap-1.5 rounded-lg border border-shell-line px-3 py-1.5 text-[0.8125rem] font-medium text-brand-navy outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
          >
            <Crosshair className="size-3.5" aria-hidden="true" />
            {w.centre}
          </button>
        ) : null}
      </div>
    </Card>
  );
}

/** How the root is tied to anything else: the shortest ways, step by step. */
function PathFinder({
  root,
  target,
  onTarget,
}: {
  root: EntityBrief;
  target: EntityBrief | null;
  onTarget: (target: EntityBrief | null) => void;
}) {
  const t = useDictionary();
  const w = t.environment.explorer;
  const paths = useGraphPaths(target ? { from: root.id, to: target.id, relationships: [] } : null);
  const [first, ...others] = paths.data?.paths ?? [];

  return (
    <Card title={w.path} icon={<IconTile icon={Route} tone="info" className="size-9" />}>
      <EntityPicker
        label={w.path}
        placeholder={w.pathPlaceholder}
        onPick={(hit) => onTarget(hit.entity)}
        testId="explorer-path"
      />
      {target && paths.data ? (
        <div className="mt-3" data-testid="explorer-path-result">
          {first ? (
            <>
              <p className="mb-2 text-xs text-shell-muted">
                {fill(w.pathLength, { count: paths.data.length ?? 0 })}
              </p>
              <ol className="space-y-1.5">
                {first.entities.map((step, index) => {
                  const link = index > 0 ? first.relationships[index - 1] : undefined;
                  const forward = link ? link.to_entity_id === step.id : true;
                  return (
                    <li key={step.id} className="text-[0.8125rem]">
                      {link ? (
                        <span className="block pl-3 text-xs text-shell-muted">
                          {forward ? "↓ " : "↑ "}
                          {t.knowledge.relationships[link.type as RelationshipType]}
                        </span>
                      ) : null}
                      <Link
                        href={entityHref({ id: step.id, type: step.type })}
                        className="font-medium text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                      >
                        {step.name}
                      </Link>
                      <span className="text-shell-muted"> · {typeLabel(t, step.type)}</span>
                    </li>
                  );
                })}
              </ol>
              {others.length ? (
                <p className="mt-2 text-xs text-shell-muted">
                  {fill(w.pathOthers, { count: others.length })}
                </p>
              ) : null}
            </>
          ) : (
            <p className="text-[0.8125rem] text-shell-muted">{w.pathNone}</p>
          )}
        </div>
      ) : null}
    </Card>
  );
}
