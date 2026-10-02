"use client";

import { UsersRound } from "lucide-react";
import Link from "next/link";
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";

import { cn } from "cn";

import { StatusBadge } from "@/components/knowledge/status-badge";
import { TONES } from "@/components/knowledge/status";
import { SourceLogo } from "@/components/sources/source-logo";
import { routes } from "@/config/routes";
import {
  entityHref,
  IconTile,
  Logo,
  typeIcon,
  type TileTone,
} from "@/components/environment/parts";
import type { EnvironmentStatus } from "@/lib/environment";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { SourceKind } from "@/lib/sources";

/** A box of the map: an entity, or a provider's cloud resources together. */
export interface MapNode {
  id: string;
  type: string;
  layer: string;
  name: string;
  status: string | null;
  entity_id: string | null;
  detail: string | null;
  count: number;
}

export interface MapEdge {
  from_id: string;
  to_id: string;
  status: string | null;
}

/** A row: its name, the kinds it holds, how many there are in all. */
export interface MapRow {
  name: string;
  types: readonly string[];
  total: number;
}

/** What to connect for an empty row: the tools that fill it. */
const HINT_LOGOS: Record<string, SourceKind[]> = {
  users: [],
  applications: ["github", "gitlab", "bitbucket"],
  code: ["github", "gitlab", "bitbucket"],
  services: ["pagerduty", "datadog", "grafana"],
  data: ["postgresql", "mysql", "aws"],
  databases: ["postgresql", "mysql", "mongodb"],
  schemas: ["postgresql", "mysql", "oracle"],
  objects: ["postgresql", "mysql", "oracle"],
  infrastructure: ["aws", "azure", "gcp"],
  accounts: ["aws", "azure", "gcp"],
  resources: ["aws", "azure", "gcp"],
  teams: ["github", "microsoft_365", "google_workspace"],
  people: ["github", "microsoft_365", "google_workspace"],
  capabilities: ["custom_rest"],
  processes: ["custom_rest"],
  business: ["custom_rest"],
};

/** Boxes a row shows before "+N": five fit the mockup's width. */
const PER_ROW = 5;

const ORDER: Record<string, number> = { incident: 0, attention: 1, operational: 2, unmonitored: 3 };

const EDGE_TONE: Record<EnvironmentStatus, keyof typeof TONES> = {
  operational: "success",
  attention: "warning",
  incident: "danger",
  unmonitored: "neutral",
};

const TILE: Record<string, TileTone> = {
  service: "violet",
  application: "violet",
  repository: "info",
  database: "success",
  schema: "success",
  data_object: "success",
  provider: "neutral",
  team: "info",
  business_capability: "warning",
  business_process: "warning",
};

interface Path {
  id: string;
  d: string;
  stroke: string;
}

/** What a row says under its name: how many, in its kind's words. */
export function rowCount(t: ReturnType<typeof useDictionary>, row: MapRow): string {
  const w = t.environment.map;
  if (row.types.length === 0) return w.noSource;
  const [only] = row.types;
  const words = row.types.length === 1 ? (w.counts as Record<string, string>)[only] : undefined;
  return fill(words ?? w.countsMixed, { count: row.total });
}

/**
 * The map of mockup 10 — and of each landscape (LEKA-369): one row per
 * layer, its name and how many it holds on the left, its things in boxes —
 * the most troubled first — and a line between two boxes of different rows
 * that are related, coloured by the worse of their states. The lines are
 * decoration: every relationship is also said on the things' own pages, in
 * the list view and on the detailed map.
 */
export function Cartography({
  nodes,
  edges,
  rows,
  all = false,
  onMore,
}: {
  nodes: readonly MapNode[];
  edges: readonly MapEdge[];
  rows: readonly MapRow[];
  /** Every box, rather than the first five of each row. */
  all?: boolean;
  onMore?: () => void;
}) {
  const t = useDictionary();
  const w = t.environment.map;
  const frame = useRef<HTMLDivElement>(null);
  const [paths, setPaths] = useState<Path[]>([]);

  // The anchor row — the services where there are, else the first that
  // holds anything — in state order, the most troubled first. Every other
  // row under or over what it is related to there, so the lines cross little.
  const byLayer = useMemo(() => {
    const grouped = new Map<string, MapNode[]>();
    for (const node of nodes) grouped.set(node.layer, [...(grouped.get(node.layer) ?? []), node]);
    const byState = (a: MapNode, b: MapNode) =>
      (ORDER[a.status ?? ""] ?? 4) - (ORDER[b.status ?? ""] ?? 4) || a.name.localeCompare(b.name);
    const anchorName = grouped.has("services")
      ? "services"
      : rows.find((row) => grouped.has(row.name))?.name;
    const anchor = (anchorName ? grouped.get(anchorName) : undefined) ?? [];
    anchor.sort(byState);
    const place = new Map(anchor.map((node, index) => [node.id, index]));
    const near = new Map<string, number[]>();
    for (const edge of edges) {
      for (const [one, other] of [
        [edge.from_id, edge.to_id],
        [edge.to_id, edge.from_id],
      ]) {
        const index = place.get(other);
        if (index !== undefined) near.set(one, [...(near.get(one) ?? []), index]);
      }
    }
    const centre = (node: MapNode) => {
      const indexes = near.get(node.id);
      return indexes ? indexes.reduce((a, b) => a + b, 0) / indexes.length : anchor.length;
    };
    for (const [layer, list] of grouped) {
      if (layer !== anchorName) list.sort((a, b) => centre(a) - centre(b) || byState(a, b));
    }
    return grouped;
  }, [nodes, edges, rows]);

  const shown = useMemo(() => {
    const ids = new Set<string>();
    for (const row of rows) {
      for (const node of (byLayer.get(row.name) ?? []).slice(0, all ? undefined : PER_ROW)) {
        ids.add(node.id);
      }
    }
    return ids;
  }, [byLayer, rows, all]);

  const drawn = useMemo(
    () => edges.filter((edge) => shown.has(edge.from_id) && shown.has(edge.to_id)),
    [edges, shown],
  );

  // Where each line goes is only known once the boxes are laid out, and
  // again whenever the frame changes width.
  const measure = useCallback(() => {
    const root = frame.current;
    if (!root) return;
    const origin = root.getBoundingClientRect();
    const box = (id: string) =>
      root.querySelector<HTMLElement>(`[data-node="${CSS.escape(id)}"]`)?.getBoundingClientRect();
    const next: Path[] = [];
    for (const edge of drawn) {
      const a = box(edge.from_id);
      const b = box(edge.to_id);
      if (!a || !b) continue;
      const [upper, lower] = a.top <= b.top ? [a, b] : [b, a];
      const x1 = upper.left + upper.width / 2 - origin.left;
      const y1 = upper.bottom - origin.top;
      const x2 = lower.left + lower.width / 2 - origin.left;
      const y2 = lower.top - origin.top;
      if (y2 <= y1) continue; // same row: the boxes sit side by side
      const middle = (y1 + y2) / 2;
      next.push({
        id: `${edge.from_id}->${edge.to_id}`,
        d: `M ${x1} ${y1} C ${x1} ${middle}, ${x2} ${middle}, ${x2} ${y2}`,
        stroke:
          TONES[EDGE_TONE[(edge.status ?? "unmonitored") as EnvironmentStatus] ?? "neutral"]
            .stroke,
      });
    }
    setPaths(next);
  }, [drawn]);

  useLayoutEffect(() => {
    measure();
    const root = frame.current;
    if (!root || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(root);
    return () => observer.disconnect();
  }, [measure]);

  return (
    <div ref={frame} className="relative" data-testid="cartography">
      <svg aria-hidden="true" className="pointer-events-none absolute inset-0 size-full">
        {paths.map((path) => (
          <path
            key={path.id}
            d={path.d}
            fill="none"
            stroke={path.stroke}
            strokeWidth={1.5}
            strokeOpacity={0.7}
          />
        ))}
      </svg>
      {rows.map((row) => {
        const members = byLayer.get(row.name) ?? [];
        const visible = all ? members : members.slice(0, PER_ROW);
        const hidden = members.length - visible.length;
        const label = (w.layers as Record<string, string>)[row.name] ?? row.name;
        return (
          <div
            key={row.name}
            className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-center gap-2 border-b border-shell-line/60 py-4 last:border-b-0"
            data-testid={`layer-${row.name}`}
          >
            <div>
              <p className="text-[0.8125rem] font-medium text-brand-navy">{label}</p>
              <p className="text-xs text-shell-muted">{rowCount(t, row)}</p>
            </div>
            <ul aria-label={label} className="flex flex-wrap items-center justify-center gap-2">
              {row.name === "users" && visible.length === 0 ? (
                <li className="relative z-10 flex items-center gap-2 rounded-lg border border-dashed border-shell-line bg-white px-3 py-2 text-xs text-shell-muted">
                  <UsersRound className="size-4" aria-hidden="true" />
                  {w.usersEmpty}
                </li>
              ) : visible.length === 0 ? (
                <li className="relative z-10 flex flex-wrap items-center gap-3 rounded-lg border border-dashed border-shell-line bg-white px-3 py-2 text-xs text-shell-muted">
                  <span className="flex gap-1.5">
                    {(HINT_LOGOS[row.name] ?? []).map((kind) => (
                      <SourceLogo key={kind} kind={kind} className="size-4" />
                    ))}
                  </span>
                  <span className="max-w-md">
                    {(w.hints as Record<string, string>)[row.name] ?? w.layerEmpty}
                  </span>
                  <Link
                    href={routes.sources()}
                    className="font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                  >
                    {w.connect}
                  </Link>
                </li>
              ) : (
                visible.map((node) => (
                  <li key={node.id}>
                    <NodeBox node={node} />
                  </li>
                ))
              )}
              {hidden > 0 ? (
                <li>
                  <button
                    type="button"
                    onClick={onMore}
                    aria-label={fill(w.moreLabel, { count: hidden })}
                    className="relative z-10 rounded-lg border border-shell-line bg-white px-3 py-2 text-xs font-medium text-shell-nav-active outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
                  >
                    {fill(w.more, { count: hidden })}
                  </button>
                </li>
              ) : null}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function NodeBox({ node }: { node: MapNode }) {
  const t = useDictionary();
  const provider = node.type === "provider";
  // A repository by its own name — payment-api of acme/payment-api — the
  // whole of it in the tooltip.
  const name = provider
    ? ((t.environment.providers as Record<string, string>)[node.name] ?? node.name)
    : node.type === "repository"
      ? (node.name.split("/").at(-1) ?? node.name)
      : node.name;
  const detail = provider
    ? [node.detail, node.count ? fill(t.environment.map.resources, { count: node.count }) : null]
        .filter(Boolean)
        .join(" · ")
    : node.detail;
  const body = (
    <>
      {provider ? (
        <span className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-shell-canvas">
          <Logo kind={node.name} className="size-5" />
        </span>
      ) : (
        <IconTile
          icon={typeIcon(node.type)}
          tone={TILE[node.type] ?? "neutral"}
          className="size-7 [&>svg]:size-4"
        />
      )}
      <span className="min-w-0">
        <span
          title={node.name}
          className="block max-w-[8rem] truncate text-[0.8125rem] font-medium text-brand-navy"
        >
          {name}
        </span>
        {detail ? (
          <span className="block max-w-[8rem] truncate text-[0.6875rem] text-shell-muted">
            {detail}
          </span>
        ) : null}
        {node.status ? (
          <StatusBadge
            variant={`entity.${node.status as EnvironmentStatus}`}
            dot
            size="sm"
            className="mt-0.5"
          />
        ) : null}
      </span>
    </>
  );
  const box =
    "relative z-10 flex min-w-[7.5rem] items-center gap-1.5 rounded-lg border bg-white px-1.5 py-1.5 text-left";
  const border =
    node.status === "incident"
      ? "border-state-danger/40 bg-state-danger-soft/40"
      : node.status === "attention"
        ? "border-state-warning/40"
        : "border-shell-line";

  if (node.entity_id) {
    return (
      <Link
        href={entityHref({ id: node.entity_id, type: node.type })}
        data-node={node.id}
        className={cn(
          box,
          border,
          "outline-none transition-shadow hover:shadow-sm focus-visible:ring-3 focus-visible:ring-brand-violet/40",
        )}
      >
        {body}
      </Link>
    );
  }
  return (
    <div data-node={node.id} className={cn(box, border)}>
      {body}
    </div>
  );
}
