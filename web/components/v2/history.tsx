"use client";

import Link from "next/link";

import { StatusPill } from "@/components/intentions/intentions-list";
import { timeAgo } from "@/components/knowledge/time";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { splitSaid } from "@/components/v2/said";
import { V2 } from "@/config/v2-routes";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { useIntentions } from "@/lib/intentions/queries";

/** Historique (2026-10-14, Lot 6): the requests made, the latest first —
 * « Mes intentions », out of the main navigation, in the avatar's menu.
 * Opened again, the exchange carries on under the bar. */
export function HistoryScreen() {
  const t = useDictionary();
  const w = t.v2.history;
  const list = useIntentions(null, "");
  const rows = list.data?.pages.flatMap((page) => page.data) ?? [];
  return (
    <div className="mx-auto w-full max-w-3xl pt-4" data-testid="v2-history">
      <title>{`${w.title} · LEKA`}</title>
      <h1 className="text-[1.75rem] leading-tight font-bold tracking-[-0.02em] text-brand-navy">{w.title}</h1>
      <p className="mt-1 text-[0.9375rem] text-shell-muted">{w.subtitle}</p>
      <div className="mt-5">
        {list.isError ? (
          <ErrorState error={list.error} onRetry={() => void list.refetch()} />
        ) : !list.data ? (
          <div className="h-40 animate-pulse rounded-2xl bg-white" aria-hidden="true" />
        ) : rows.length === 0 ? (
          <p className="rounded-2xl bg-white px-4 py-6 text-center text-[0.9375rem] text-shell-muted ring-1 ring-shell-line">
            {w.empty}
          </p>
        ) : (
          <ul className="divide-y divide-shell-line overflow-hidden rounded-2xl bg-white ring-1 ring-shell-line">
            {rows.map((row) => (
              <li key={row.id}>
                <Link
                  href={V2.thread(row.id)}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-inset focus-visible:ring-brand-violet/40"
                  data-testid="v2-history-row"
                >
                  <span className="min-w-0 flex-1 truncate text-[0.9375rem] font-medium text-brand-navy" dir="auto">
                    {splitSaid(row.text)[0] ?? row.title}
                  </span>
                  <StatusPill status={row.status} journey={row.journey} />
                  <span className="text-xs text-shell-muted">{timeAgo(t, row.updated_at)}</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
        {list.hasNextPage ? (
          <div className="mt-3 flex justify-center">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={list.isFetchingNextPage}
              onClick={() => void list.fetchNextPage()}
            >
              {w.more}
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
