"use client";

import { useQuery } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";
import { knowledgeQuality, type QualityLevel } from "@/lib/knowledge-quality";

export const qualityKeys = {
  summary: ["intelligence", "quality"] as const,
  weakest: (level: QualityLevel | null) => ["intelligence", "quality", "weakest", level] as const,
  one: (key: string) => ["intelligence", "quality", "score", key] as const,
};

export function useQualitySummary() {
  return useQuery({ queryKey: qualityKeys.summary, queryFn: knowledgeQuality.summary });
}

export function useWeakest(level: QualityLevel | null) {
  return useQuery({
    queryKey: qualityKeys.weakest(level),
    queryFn: () => knowledgeQuality.weakest(level ?? undefined),
  });
}

/** One thing's score — none (404) until a run measured it. */
export function useEntityQuality(id: string | null) {
  const key = id ? `entity:${id}` : "";
  return useQuery({
    queryKey: qualityKeys.one(key),
    queryFn: async () => {
      try {
        return await knowledgeQuality.one(key);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    enabled: Boolean(id),
  });
}
