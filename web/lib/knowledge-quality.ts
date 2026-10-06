/**
 * How far what LEKA knows can be trusted (LEKA-381): a score for each thing
 * and each area — the workspace, a column of Mon environnement, a team, an
 * application — on four dimensions, what lowers it, and how it moved. The
 * shapes are the generated ones; api/leka/api/intelligence.py says what
 * each route answers, docs/intelligence.md § 15 how a score is made.
 */

import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

export type QualitySummary = components["schemas"]["KnowledgeQualitySummary"];
export type QualityScore = components["schemas"]["KnowledgeQualityRead"];
export type QualityDetail = components["schemas"]["KnowledgeQualityDetail"];
export type QualityPoint = components["schemas"]["KnowledgeQualityPoint"];
export type QualityLevel = QualityScore["level"];

export const DIMENSIONS = ["completeness", "freshness", "consistency", "confidence"] as const;
export type Dimension = (typeof DIMENSIONS)[number];

export interface QualityPage {
  data: QualityScore[];
  next_cursor: string | null;
}

const BASE = "/intelligence/quality";

/** What lowers a score: a thing's {code, dimension, weight, detail}, an
 * area's {code, count}. */
export interface Lack {
  code: string;
  dimension: Dimension | null;
  count: number | null;
}

export function lacksOf(score: Pick<QualityScore, "missing">): Lack[] {
  return score.missing.map((item) => ({
    code: String(item.code ?? ""),
    dimension: (DIMENSIONS as readonly unknown[]).includes(item.dimension)
      ? (item.dimension as Dimension)
      : null,
    count: typeof item.count === "number" ? item.count : null,
  }));
}

export const knowledgeQuality = {
  /** The workspace's, by area, the weakest things, the trend. */
  summary: () => apiFetch<QualitySummary>(BASE),
  /** The things measured, the weakest first — 100 at most. */
  weakest: (level?: QualityLevel) =>
    apiFetch<QualityPage>(
      `${BASE}/scores?scope=entity&sort=score&order=asc&limit=100${level ? `&level=${level}` : ""}`,
    ),
  /** One score, its factors and history: `entity:<id>`, `team:<id>`… */
  one: (key: string) => apiFetch<QualityDetail>(`${BASE}/scores/${encodeURIComponent(key)}`),
};
