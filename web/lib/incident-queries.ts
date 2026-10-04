"use client";

import { useQuery } from "@tanstack/react-query";

import { incidents } from "@/lib/incidents";

export const incidentKeys = {
  detail: (id: string) => ["incident", id] as const,
};

export function useIncident(id: string) {
  return useQuery({ queryKey: incidentKeys.detail(id), queryFn: () => incidents.detail(id) });
}
