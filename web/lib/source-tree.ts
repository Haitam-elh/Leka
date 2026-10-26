/**
 * « Arborescence » (2026-10-25): what a Confluence source synced, space by
 * space — its pages parent and child, how many, how deep — to check that
 * everything came up. GET /sources/{id}/tree; never a page's text.
 */

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type SourceTree = components["schemas"]["SourceTreeRead"];
export type TreeSpace = components["schemas"]["TreeSpaceRead"];
export type TreeNode = components["schemas"]["TreeNodeRead"];

export const sourceTree = {
  read: (sourceId: string) => apiFetch<SourceTree>(`/sources/${encodeURIComponent(sourceId)}/tree`),
};

export function useSourceTree(sourceId: string | null) {
  return useQuery({
    queryKey: ["sources", "tree", sourceId],
    queryFn: () => sourceTree.read(sourceId as string),
    enabled: Boolean(sourceId),
  });
}

/** Its pages in reading order, each with its depth — for a list to choose from. */
export function flattened(nodes: TreeNode[], depth = 0): { node: TreeNode; depth: number }[] {
  return nodes.flatMap((node) => [{ node, depth }, ...flattened(node.children ?? [], depth + 1)]);
}
