"use client";

import {
  Background,
  type Edge,
  Handle,
  MarkerType,
  type Node,
  type NodeProps,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import { Maximize, Network, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import { useId, useMemo } from "react";

import { cn } from "cn";

import { EntityCard } from "@/components/knowledge/entity-card";
import { TONES, type Tone } from "@/components/knowledge/status";
import { StatePanel } from "@/components/states/state-panel";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type {
  EntityStatus,
  EntityType,
  KnowledgeEntity,
  KnowledgeRelationship,
} from "@/lib/knowledge";

const NODE_WIDTH = 190;
const NODE_HEIGHT = 58;
const COLUMN_GAP = 30;
const ROW_GAP = 70;

/**
 * Rows, top to bottom, in the order mockup 10 draws them: who uses it, what
 * runs, what it is made of, where data lives, what it runs on.
 */
const LAYER: Record<EntityType, number> = {
  person: 0,
  team: 0,
  application: 1,
  service: 1,
  repository: 2,
  deployment: 2,
  incident: 2,
  document: 2,
  project: 2,
  issue: 2,
  pull_request: 2,
  commit: 2,
  release: 2,
  database: 3,
  infra_resource: 4,
  environment: 4,
  // What resources are in: under them, with them (LEKA-363).
  cloud_account: 4,
  resource_group: 4,
  // A database's schemas and tables, beside it (LEKA-364).
  schema: 3,
  data_object: 3,
  // Where documents are kept, with them; what the business does, above
  // what supports it (LEKA-366).
  knowledge_space: 2,
  business_capability: 0,
  business_process: 0,
  // What changed, with what was shipped (LEKA-367).
  change: 2,
};

/** Past this many, a layer wraps onto another row: 80 services side by side
 * fit the screen only as an unreadable strip. */
const MAX_COLUMNS = 10;

/**
 * Where each entity goes when the caller gives no positions: its layer's
 * rows, top to bottom, each at most MAX_COLUMNS wide and centred.
 * Deterministic, and nothing more.
 *
 * TODO LEKA-340 follow-up: a real auto-layout (dagre or elkjs) that
 * minimises crossings. Not a dependency yet — the positions come from the
 * props when the layout matters.
 */
export function layeredPositions(
  entities: readonly KnowledgeEntity[],
): Record<string, { x: number; y: number }> {
  const layers = new Map<number, KnowledgeEntity[]>();
  for (const entity of entities) {
    const layer = LAYER[entity.type];
    layers.set(layer, [...(layers.get(layer) ?? []), entity]);
  }
  return rowPositions([...layers.keys()].sort((a, b) => a - b).map((l) => layers.get(l) ?? []));
}

/**
 * Groups made readable (LEKA-369): each group split into rows by what
 * points to what inside it — what nothing of the group points to on top,
 * what it points to under it, so that an arrow goes down a row rather than
 * along one, where it would loop over its neighbours — then each row
 * ordered under what it is tied to above it, so the lines cross little. A
 * loop is cut where it closes. Forty tables and their foreign keys: the
 * tables everything references at the bottom, the arrows going down.
 */
export function layered<T extends { id: string }>(
  groups: readonly (readonly T[])[],
  links: readonly { from: string; to: string }[],
): T[][] {
  const rows: T[][] = [];
  for (const group of groups) {
    const inGroup = new Set(group.map((one) => one.id));
    const pointedBy = new Map<string, string[]>();
    for (const link of links) {
      if (link.from === link.to || !inGroup.has(link.from) || !inGroup.has(link.to)) continue;
      pointedBy.set(link.to, [...(pointedBy.get(link.to) ?? []), link.from]);
    }
    const rank = new Map<string, number>();
    const visiting = new Set<string>();
    const rankOf = (id: string): number => {
      const known = rank.get(id);
      if (known !== undefined) return known;
      visiting.add(id);
      let deepest = 0;
      for (const from of pointedBy.get(id) ?? []) {
        // A loop: cut where it closes.
        if (!visiting.has(from)) deepest = Math.max(deepest, rankOf(from) + 1);
      }
      visiting.delete(id);
      rank.set(id, deepest);
      return deepest;
    };
    const levels = new Map<number, T[]>();
    for (const one of group) {
      const level = rankOf(one.id);
      levels.set(level, [...(levels.get(level) ?? []), one]);
    }
    for (const level of [...levels.keys()].sort((a, b) => a - b)) {
      rows.push(levels.get(level) ?? []);
    }
  }

  // Each row under what it is tied to above it: by the mean place of those.
  const neighbours = new Map<string, string[]>();
  for (const link of links) {
    neighbours.set(link.from, [...(neighbours.get(link.from) ?? []), link.to]);
    neighbours.set(link.to, [...(neighbours.get(link.to) ?? []), link.from]);
  }
  const place = new Map<string, number>();
  return rows.map((row, index) => {
    const ordered =
      index === 0
        ? row
        : row
            .map((one, at) => {
              const above = (neighbours.get(one.id) ?? [])
                .map((id) => place.get(id))
                .filter((x): x is number => x !== undefined);
              const centre = above.length
                ? above.reduce((a, b) => a + b, 0) / above.length
                : Number.POSITIVE_INFINITY;
              return { one, at, centre };
            })
            .sort((a, b) => a.centre - b.centre || a.at - b.at)
            .map(({ one }) => one);
    ordered.forEach((one, at) => place.set(one.id, (at + 0.5) / ordered.length));
    return ordered;
  });
}

/**
 * Where each entity goes when the caller groups them: each group its own
 * rows, top to bottom, at most MAX_COLUMNS wide and centred — a walk's
 * distances from its root, a view's layers (LEKA-369).
 */
export function rowPositions(
  groups: readonly (readonly { id: string }[])[],
): Record<string, { x: number; y: number }> {
  const rows: (readonly { id: string }[])[] = [];
  for (const members of groups) {
    for (let start = 0; start < members.length; start += MAX_COLUMNS) {
      rows.push(members.slice(start, start + MAX_COLUMNS));
    }
  }

  const widest = Math.max(0, ...rows.map((row) => row.length));
  const positions: Record<string, { x: number; y: number }> = {};
  rows.forEach((row, rowIndex) => {
    const offset = ((widest - row.length) * (NODE_WIDTH + COLUMN_GAP)) / 2;
    row.forEach((entity, column) => {
      positions[entity.id] = {
        x: offset + column * (NODE_WIDTH + COLUMN_GAP),
        y: rowIndex * (NODE_HEIGHT + ROW_GAP),
      };
    });
  });
  return positions;
}

const EDGE_TONE: Record<EntityStatus, Tone> = {
  operational: "success",
  attention: "warning",
  incident: "danger",
  unmonitored: "neutral",
  unknown: "neutral",
};

/**
 * The edges React Flow draws: one per relationship whose two ends are on the
 * map, coloured by its status, arrowed in its direction, named in words. A
 * relationship to an entity that is not shown is dropped rather than drawn
 * to nowhere.
 */
export function graphEdges(
  entities: readonly KnowledgeEntity[],
  relationships: readonly KnowledgeRelationship[],
  relation: (type: KnowledgeRelationship["type"]) => string,
): Edge[] {
  const names = new Map(entities.map((entity) => [entity.id, entity.name]));
  return relationships
    .filter((link) => names.has(link.from) && names.has(link.to))
    .map((link) => {
      const stroke = TONES[EDGE_TONE[link.status ?? "unknown"]].stroke;
      return {
        id: link.id,
        source: link.from,
        target: link.to,
        ariaLabel: `${names.get(link.from)} ${relation(link.type)} ${names.get(link.to)}`,
        focusable: false,
        style: { stroke, strokeWidth: 1.5 },
        markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 16, height: 16 },
        data: { status: link.status ?? "unknown" },
      };
    });
}

type EntityNodeData = {
  entity: KnowledgeEntity;
  selected: boolean;
  onOpen?: (id: string) => void;
};

function EntityNode({ data }: NodeProps<Node<EntityNodeData, "entity">>) {
  return (
    <div style={{ width: NODE_WIDTH }}>
      <Handle type="target" position={Position.Top} isConnectable={false} className="opacity-0" />
      <EntityCard
        {...data.entity}
        compact
        selected={data.selected}
        onClick={data.onOpen}
        className="shadow-sm"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        isConnectable={false}
        className="opacity-0"
      />
    </div>
  );
}

const NODE_TYPES = { entity: EntityNode };

export interface DependencyGraphProps {
  entities: readonly KnowledgeEntity[];
  relationships: readonly KnowledgeRelationship[];
  /** Where each node sits. Missing ones are laid out in layers by type. */
  positions?: Record<string, { x: number; y: number }>;
  onNodeClick?: (id: string) => void;
  selectedId?: string;
  /** 480px by default. */
  height?: number | string;
  /** Nodes cannot be dragged. True by default: this is a map, not an editor. */
  readOnly?: boolean;
  className?: string;
}

function Controls() {
  const t = useDictionary();
  const flow = useReactFlow();
  const buttons = [
    { label: t.knowledge.graph.zoomIn, icon: ZoomIn, run: () => void flow.zoomIn() },
    { label: t.knowledge.graph.zoomOut, icon: ZoomOut, run: () => void flow.zoomOut() },
    {
      label: t.knowledge.graph.fit,
      icon: Maximize,
      run: () => void flow.fitView({ padding: 0.2 }),
    },
    {
      label: t.knowledge.graph.reset,
      icon: RotateCcw,
      run: () => void flow.setViewport({ x: 0, y: 0, zoom: 1 }),
    },
  ];
  return (
    <Panel position="top-right">
      <div className="flex flex-col overflow-hidden rounded-lg border border-shell-line bg-white shadow-sm">
        {buttons.map(({ label, icon: Icon, run }) => (
          <button
            key={label}
            type="button"
            onClick={run}
            aria-label={label}
            title={label}
            className="flex size-8 items-center justify-center text-shell-icon outline-none hover:bg-brand-violet-soft/60 hover:text-shell-nav-active focus-visible:ring-2 focus-visible:ring-brand-violet/40 focus-visible:ring-inset"
          >
            <Icon aria-hidden="true" className="size-4" />
          </button>
        ))}
      </div>
    </Panel>
  );
}

function Graph({
  entities,
  relationships,
  positions,
  onNodeClick,
  selectedId,
  readOnly,
}: DependencyGraphProps) {
  const t = useDictionary();

  const nodes = useMemo<Node<EntityNodeData, "entity">[]>(() => {
    const fallback = layeredPositions(entities);
    return entities.map((entity) => ({
      id: entity.id,
      type: "entity",
      position: positions?.[entity.id] ?? fallback[entity.id],
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
      data: { entity, selected: entity.id === selectedId, onOpen: onNodeClick },
      // The card's name is the button; the node itself need not take focus.
      focusable: false,
      selectable: false,
    }));
  }, [entities, positions, selectedId, onNodeClick]);

  const edges = useMemo(
    () => graphEdges(entities, relationships, (type) => t.knowledge.relationships[type]),
    [entities, relationships, t],
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      fitView
      fitViewOptions={{ padding: 0.2 }}
      minZoom={0.1}
      maxZoom={2}
      nodesDraggable={!readOnly}
      nodesConnectable={false}
      elementsSelectable={false}
      // Past a hundred nodes, draw only what is on screen.
      onlyRenderVisibleElements={entities.length > 100}
    >
      <Background gap={24} size={1} color="var(--shell-line)" />
      <Controls />
    </ReactFlow>
  );
}

/**
 * Entities and their relationships as a map (LEKA-340) — the
 * "Cartographie" of mockup 10, on React Flow.
 *
 * Nodes are compact EntityCards; edges take the colour of the relationship's
 * status, and an arrow for its direction. Zoom, fit and reset are buttons
 * with words, and the whole graph is also written out, for screen readers,
 * as two lists: what there is, and how it is linked.
 */
export function DependencyGraph(props: DependencyGraphProps) {
  const t = useDictionary();
  const titleId = useId();
  const { entities, relationships, height = 480, className } = props;

  if (entities.length === 0) {
    return (
      <StatePanel
        icon={Network}
        size="section"
        headingLevel={3}
        title={t.knowledge.graph.empty}
        className={className}
      />
    );
  }

  const names = new Map(entities.map((entity) => [entity.id, entity.name]));
  const described = relationships.filter((link) => names.has(link.from) && names.has(link.to));

  return (
    <section
      aria-labelledby={titleId}
      data-slot="dependency-graph"
      className={cn(
        "relative overflow-hidden rounded-xl border border-shell-line bg-white",
        className,
      )}
      style={{ height }}
    >
      <h3 id={titleId} className="sr-only">
        {`${t.knowledge.graph.label} — ${fill(t.knowledge.graph.summary, {
          entities: entities.length,
          relationships: described.length,
        })}`}
      </h3>
      <ReactFlowProvider>
        <Graph {...props} readOnly={props.readOnly ?? true} />
      </ReactFlowProvider>
      <div className="sr-only" data-testid="graph-text">
        <ul>
          {entities.map((entity) => (
            <li key={entity.id}>
              {[
                entity.name,
                t.knowledge.entityTypes[entity.type],
                entity.status ? t.knowledge.status.entity[entity.status] : null,
              ]
                .filter(Boolean)
                .join(", ")}
            </li>
          ))}
        </ul>
        <ul>
          {described.map((link) => (
            <li key={link.id}>
              {`${names.get(link.from)} ${t.knowledge.relationships[link.type]} ${names.get(link.to)}`}
              {link.status ? ` (${t.knowledge.status.entity[link.status]})` : null}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
