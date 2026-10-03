/**
 * The knowledge graph, as the screens explore it (LEKA-369): search, a walk
 * around some entities, the shortest ways between two, the company's
 * landscapes — each with how well the model knows its kinds. The shapes are
 * the generated ones; api/leka/api/graph.py says what each route answers.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";
import type { EntityType, RelationshipType } from "@/lib/knowledge";

export type SearchResults = components["schemas"]["SearchResults"];
export type SearchHit = components["schemas"]["SearchHit"];
export type GraphRead = components["schemas"]["GraphRead"];
export type GraphNode = components["schemas"]["GraphNodeRead"];
export type PathsRead = components["schemas"]["PathsRead"];
export type LandscapeView = components["schemas"]["LandscapeViewRead"];
export type ViewLayer = components["schemas"]["ViewLayerRead"];
export type ViewNode = components["schemas"]["ViewNodeRead"];
export type ViewEdge = components["schemas"]["ViewEdgeRead"];
export type KindCoverage = components["schemas"]["KindCoverageRead"];
export type ViewSource = components["schemas"]["ViewSourceRead"];
export type EntityBrief = components["schemas"]["EntityBrief"];
export type Architecture = components["schemas"]["ArchitectureRead"];
export type ArchitectureCard = components["schemas"]["ArchitectureCardRead"];
export type ArchitectureLink = components["schemas"]["ArchitectureLinkRead"];
export type ArchitectureBundle = components["schemas"]["ArchitectureBundleRead"];
export type ArchitectureGroup = components["schemas"]["ArchitectureGroupRead"];

/** The architecture's columns, left to right (api/leka/knowledge/architecture.py). */
export const ARCHITECTURE_COLUMNS = ["code", "services", "data", "cloud", "external"] as const;
export type ArchitectureColumn = (typeof ARCHITECTURE_COLUMNS)[number];

/** The landscapes, as the API names them — the tabs of "Mon environnement",
 * and the dependency view of the detailed map. */
export const VIEWS = [
  "company",
  "domains",
  "applications",
  "services",
  "data",
  "infrastructure",
  "organisation",
  "dependencies",
] as const;
export type ViewName = (typeof VIEWS)[number];

export type Direction = "both" | "outgoing" | "incoming";

export interface WalkParams {
  root: string;
  depth: number;
  direction: Direction;
  /** Only through these; every kind when empty. */
  relationships: readonly RelationshipType[];
}

export interface PathParams {
  from: string;
  to: string;
  relationships: readonly RelationshipType[];
}

function query(params: Record<string, string | number | readonly string[] | undefined>): string {
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(params)) {
    if (value === undefined) continue;
    if (Array.isArray(value)) {
      for (const one of value) search.append(name, String(one));
    } else {
      search.append(name, String(value));
    }
  }
  return search.toString();
}

export const knowledgeGraph = {
  search: (q: string, options: { types?: readonly EntityType[]; limit?: number } = {}) =>
    apiFetch<SearchResults>(
      `/knowledge/search?${query({ q, type: options.types, limit: options.limit })}`,
    ),
  walk: (params: WalkParams) =>
    apiFetch<GraphRead>(
      `/knowledge/graph?${query({
        root: params.root,
        depth: params.depth,
        direction: params.direction,
        relationship: params.relationships,
      })}`,
    ),
  paths: (params: PathParams) =>
    apiFetch<PathsRead>(
      `/knowledge/graph/paths?${query({
        from: params.from,
        to: params.to,
        relationship: params.relationships,
      })}`,
    ),
  view: (name: ViewName) => apiFetch<LandscapeView>(`/knowledge/views/${name}`),
  architecture: (environment: string | null) =>
    apiFetch<Architecture>(
      `/knowledge/architecture${environment ? `?${query({ environment })}` : ""}`,
    ),
};

/**
 * What the detailed map's "Relations" filter offers: families of
 * relationship kinds, as someone exploring thinks of them.
 */
export const RELATION_FAMILIES = {
  all: [],
  dependencies: ["depends_on", "supported_by", "uses", "reads_from", "references"],
  structure: ["part_of", "child_of", "runs_in", "in_network", "realizes"],
  people: [
    "owned_by",
    "maintained_by",
    "member_of",
    "led_by",
    "reports_to",
    "contributes_to",
  ],
  operations: ["affects", "caused_by", "deploys", "deployed_to", "resolves", "implements"],
} as const satisfies Record<string, readonly RelationshipType[]>;
export type RelationFamily = keyof typeof RELATION_FAMILIES;
