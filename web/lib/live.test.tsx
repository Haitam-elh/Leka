/**
 * Nothing on screen is left as it was read (2026-10-29, Haitam: « à chaque
 * fois que je recharge pour que ça fonctionne »).
 *
 * What these protect: every query read again while its tab is in view, and
 * when it comes back; an intention that changes — answered, asked again,
 * analysed — has everything else on its page read again at once.
 */
import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { IntentionDetail } from "@/lib/intentions/api";
import { intentionKeys, useFollowIntention } from "@/lib/intentions/queries";
import { LIVE_EVERY } from "@/lib/live";
import { makeQueryClient } from "@/lib/query";

function intention(version: number, status = "needs_clarification"): IntentionDetail {
  return { id: "i1", version, status, updated_at: `2026-10-29T10:0${version}:00Z` } as IntentionDetail;
}

describe("live", () => {
  it("reads every query again while it is in view, and when its tab comes back", () => {
    const queries = makeQueryClient().getDefaultOptions().queries;
    expect(queries?.refetchInterval).toBe(LIVE_EVERY);
    expect(queries?.refetchIntervalInBackground).toBeFalsy();
    expect(queries?.refetchOnWindowFocus).toBe(true);
  });

  it("reads the rest of an intention's page again the moment it changes", () => {
    const client = makeQueryClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const { rerender } = renderHook(({ shown }) => useFollowIntention(shown), {
      initialProps: { shown: intention(1) },
      wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>,
    });
    // As first read: nothing to read again.
    expect(invalidate).not.toHaveBeenCalled();
    rerender({ shown: intention(1) });
    expect(invalidate).not.toHaveBeenCalled();
    // Answered: a new version.
    rerender({ shown: intention(2, "analysing") });
    expect(invalidate).toHaveBeenCalledTimes(1);
    const { predicate } = invalidate.mock.calls[0][0] as {
      predicate: (query: { queryKey: readonly unknown[] }) => boolean;
    };
    expect(predicate({ queryKey: intentionKeys.routing("i1") })).toBe(true);
    // Never itself: it is what was just read.
    expect(predicate({ queryKey: intentionKeys.one("i1") })).toBe(false);
  });
});
