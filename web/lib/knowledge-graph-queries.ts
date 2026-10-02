"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { isEntityId } from "@/lib/environment";
import {
  knowledgeGraph,
  type PathParams,
  type ViewName,
  type WalkParams,
} from "@/lib/knowledge-graph";

/** The knowledge graph as queries (LEKA-369). */
export const graphKeys = {
  all: ["knowledge-graph"] as const,
  search: (q: string) => [...graphKeys.all, "search", q] as const,
  walk: (params: WalkParams) => [...graphKeys.all, "walk", params] as const,
  paths: (params: PathParams) => [...graphKeys.all, "paths", params] as const,
  view: (name: ViewName) => [...graphKeys.all, "view", name] as const,
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
    enabled: params !== null && isEntityId(params.root),
    placeholderData: keepPreviousData,
  });
}

export function useGraphPaths(params: PathParams | null) {
  return useQuery({
    queryKey: params ? graphKeys.paths(params) : graphKeys.all,
    queryFn: () => knowledgeGraph.paths(params as PathParams),
    enabled: params !== null && isEntityId(params.from) && isEntityId(params.to),
  });
}

export function useLandscapeView(name: ViewName | null) {
  return useQuery({
    queryKey: graphKeys.view(name ?? "company"),
    queryFn: () => knowledgeGraph.view(name ?? "company"),
    enabled: name !== null,
  });
}
