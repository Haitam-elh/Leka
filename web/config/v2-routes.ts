/**
 * The new interface's addresses (2026-10-14, the product call's Lot 6), at
 * /v2 beside the current one. Kept apart from config/routes.ts: that
 * registry is the current interface's — its sidebar, breadcrumb and guard —
 * and the new one has none of them.
 */
export const V2 = {
  home: "/v2",
  /** An exchange with LEKA: one intention, its thread under the bar. */
  thread: (intentionId: string) => `/v2?i=${encodeURIComponent(intentionId)}`,
  agents: "/v2/agents",
  history: "/v2/history",
} as const;
