"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError } from "@/lib/api";
import { LIVE_EVERY } from "@/lib/live";

/**
 * TanStack Query, for the screens that read AND change what they show
 * (LEKA-345's sources first). A mutation invalidates the queries it made
 * stale, and every view of that data refreshes — no screen keeps its own
 * copy to forget to update.
 *
 * Retries: once, and never for an answer that will not change by asking
 * again — a refusal (4xx) is the API's decision, not a hiccup.
 *
 * Live (2026-10-29): every query is read again every LIVE_EVERY while its
 * tab is in view, and at once when the tab comes back — what LEKA did is
 * on screen without reloading. What follows something faster says so.
 */
function retry(failures: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failures < 1;
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry,
        staleTime: 5_000,
        refetchInterval: LIVE_EVERY,
        refetchOnWindowFocus: true,
        refetchOnReconnect: true,
      },
      mutations: { retry: false },
    },
  });
}

export function QueryProvider({ children }: { children: React.ReactNode }) {
  // One client per browser session, not per render.
  const [client] = useState(makeQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
