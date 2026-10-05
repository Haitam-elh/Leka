"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { contexts } from "@/lib/context";

/** The context engine as queries (LEKA-370). */
export const contextKeys = {
  all: ["context"] as const,
  ofEntity: (entityId: string) => [...contextKeys.all, "entity", entityId] as const,
  detail: (id: string) => [...contextKeys.all, "detail", id] as const,
  versions: (id: string) => [...contextKeys.all, "versions", id] as const,
  assembled: (id: string, version: number | null) =>
    [...contextKeys.all, "assembled", id, version] as const,
  diff: (id: string, from: number, to: number) =>
    [...contextKeys.all, "diff", id, from, to] as const,
  checks: (id: string) => [...contextKeys.all, "checks", id] as const,
  quality: (id: string, version: number | null) =>
    [...contextKeys.all, "quality", id, version] as const,
  element: (id: string, refId: string, version: number | null) =>
    [...contextKeys.all, "element", id, refId, version] as const,
  evidence: (id: string, refId: string, version: number | null) =>
    [...contextKeys.all, "evidence", id, refId, version] as const,
};

export function useEntityContexts(entityId: string) {
  return useQuery({
    queryKey: contextKeys.ofEntity(entityId),
    queryFn: () => contexts.ofEntity(entityId),
  });
}

export function useContextVersions(id: string | null) {
  return useQuery({
    queryKey: contextKeys.versions(id ?? ""),
    queryFn: () => contexts.versions(id ?? ""),
    enabled: id !== null,
  });
}

/** A version whole — the latest that holds something when `version` is null. */
export function useAssembledContext(id: string | null, version: number | null) {
  return useQuery({
    queryKey: contextKeys.assembled(id ?? "", version),
    queryFn: () => contexts.assembled(id ?? "", version ?? undefined),
    enabled: id !== null,
  });
}

export function useContextDiff(id: string | null, pair: readonly [number, number] | null) {
  return useQuery({
    queryKey: contextKeys.diff(id ?? "", pair?.[0] ?? 0, pair?.[1] ?? 0),
    queryFn: () => contexts.diff(id ?? "", pair?.[0] ?? 0, pair?.[1] ?? 0),
    enabled: id !== null && pair !== null,
  });
}

/** Every time a context was made again, and what came of it (LEKA-374). */
export function useContextChecks(id: string | null) {
  return useQuery({
    queryKey: contextKeys.checks(id ?? ""),
    queryFn: () => contexts.checks(id ?? ""),
    enabled: id !== null,
  });
}

/** How good a version is, and what people said of it (LEKA-375). */
export function useContextQuality(id: string | null, version: number | null) {
  return useQuery({
    queryKey: contextKeys.quality(id ?? "", version),
    queryFn: () => contexts.quality(id ?? "", version ?? undefined),
    enabled: id !== null,
  });
}

/** One element of a version, inspected (LEKA-376). */
export function useElementInspection(id: string, refId: string, version: number | null) {
  return useQuery({
    queryKey: contextKeys.element(id, refId, version),
    queryFn: () => contexts.inspect(id, refId, version ?? undefined),
  });
}

/** The records an element was read from — read when asked. */
export function useElementEvidence(
  id: string,
  refId: string,
  version: number | null,
  asked: boolean,
) {
  return useQuery({
    queryKey: contextKeys.evidence(id, refId, version),
    queryFn: () => contexts.evidence(id, refId, version ?? undefined),
    enabled: asked,
  });
}

/** What happens to a context, as it happens (LEKA-376): what is shown read
 * again when it changes. `onUpdate` hears each time LEKA made it again on
 * its own. Nothing where the browser has no EventSource. */
export function useContextEvents(
  id: string | null,
  onUpdate?: (check: { version: number; trigger: string }) => void,
) {
  const client = useQueryClient();
  const heard = useRef(onUpdate);
  useEffect(() => {
    heard.current = onUpdate;
  }, [onUpdate]);
  useEffect(() => {
    if (id === null || typeof EventSource === "undefined") return;
    const source = new EventSource(contexts.events(id), { withCredentials: true });
    const refresh = () => void client.invalidateQueries({ queryKey: contextKeys.all });
    // Said at every (re)connection: read again only when it moved.
    let fresh: string | null = null;
    const freshness = (event: MessageEvent<string>) => {
      if (fresh !== null && fresh !== event.data) refresh();
      fresh = event.data;
    };
    const checked = (event: MessageEvent<string>) => {
      refresh();
      try {
        const check = JSON.parse(event.data) as {
          version: number;
          trigger: string;
          outcome: string;
          checked_by: string | null;
        };
        if (check.checked_by === null && check.outcome === "version") heard.current?.(check);
      } catch {
        // A check that says nothing readable still refreshed what is shown.
      }
    };
    source.addEventListener("check", checked as EventListener);
    source.addEventListener("freshness", freshness as EventListener);
    source.addEventListener("archived", refresh);
    return () => source.close();
  }, [id, client]);
}

/** Any action on a context; everything about contexts is read again after. */
export function useContextMutation<TArgs, TResult>(run: (args: TArgs) => Promise<TResult>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSettled: () => client.invalidateQueries({ queryKey: contextKeys.all }),
  });
}
