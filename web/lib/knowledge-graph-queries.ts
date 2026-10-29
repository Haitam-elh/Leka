"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { isEntityId } from "@/lib/environment";
import {
  knowledgeGraph,
  type PathParams,
  type ViewName,
  type WalkParams,
} from "@/lib/knowledge-graph";
import { LIVE_SLOW } from "@/lib/live";

/** The knowledge graph as queries (LEKA-369). */
export const graphKeys = {
  all: ["knowledge-graph"] as const,
  search: (q: string) => [...graphKeys.all, "search", q] as const,
  walk: (params: WalkParams) => [...graphKeys.all, "walk", params] as const,
  paths: (params: PathParams) => [...graphKeys.all, "paths", params] as const,
  view: (name: ViewName) => [...graphKeys.all, "view", name] as const,
  architecture: (environment: string | null, detailed = false) =>
    [...graphKeys.all, "architecture", environment ?? "", detailed] as const,
};

/** Searching starts at two letters: one matches half the company. */
export const MIN_SEARCH = 2;

export function useGraphSearch(q: string) {
  const typed = q.trim();
  return useQuery({
    queryKey: graphKeys.search(typed),
    queryFn: () => knowledgeGraph.search(typed, { limit: 8 }),
    enabled: typed.length >= MIN_SEARCH,
    placeholderData: keepPreviousData,
  });
}

/** A walk asks nothing until its root is an entity's id. */
export function useGraphWalk(params: WalkParams | null) {
  return useQuery({
    queryKey: params ? graphKeys.walk(params) : graphKeys.all,
    queryFn: () => knowledgeGraph.walk(params as WalkParams),
    refetchInterval: LIVE_SLOW,
    enabled: params !== null && isEntityId(params.root),
    placeholderData: keepPreviousData,
  });
}

export function useGraphPaths(params: PathParams | null) {
  return useQuery({
    queryKey: params ? graphKeys.paths(params) : graphKeys.all,
    queryFn: () => knowledgeGraph.paths(params as PathParams),
    refetchInterval: LIVE_SLOW,
    enabled: params !== null && isEntityId(params.from) && isEntityId(params.to),
  });
}

export function useLandscapeView(name: ViewName | null) {
  return useQuery({
    queryKey: graphKeys.view(name ?? "company"),
    queryFn: () => knowledgeGraph.view(name ?? "company"),
    refetchInterval: LIVE_SLOW,
    enabled: name !== null,
  });
}

/** What the company runs, in columns — one environment's, or all of it;
 * detailed: every card, its flows, what to confirm, its sources. */
export function useArchitecture(environment: string | null, enabled = true, detailed = false) {
  return useQuery({
    queryKey: graphKeys.architecture(environment, detailed),
    queryFn: () => knowledgeGraph.architecture(environment, detailed),
    refetchInterval: LIVE_SLOW,
    enabled,
    placeholderData: keepPreviousData,
  });
}
