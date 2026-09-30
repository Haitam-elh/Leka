"use client";

import { useQuery } from "@tanstack/react-query";

import { environment, isEntityId } from "@/lib/environment";

/** The environment as queries (LEKA-359): the screen, and an entity's sheet. */
export const environmentKeys = {
  all: ["environment"] as const,
  sheet: (id: string) => [...environmentKeys.all, "sheet", id] as const,
};

export function useEnvironment() {
  return useQuery({ queryKey: environmentKeys.all, queryFn: environment.get });
}

/** An id that is not an entity's asks nothing: the page says it found none. */
export function useEntitySheet(id: string) {
  return useQuery({
    queryKey: environmentKeys.sheet(id),
    queryFn: () => environment.sheet(id),
    enabled: isEntityId(id),
  });
}
