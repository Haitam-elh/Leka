"use client";

import { Activity, ListChecks } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Card } from "@/components/environment/parts";
import { exactDate } from "@/components/knowledge/time";
import { Button } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { useAgentJournal, useAgentUsage } from "@/lib/security-queries";

/**
 * Sécurité & gouvernance › Usage des agents (2026-10-25): how many times
 * each agent ran over a period — counted, never priced — and the journal of
 * its runs: who ran which agent, on what, held to which sources, when, how
 * it ended. For who may read the audit trail.
 */

const PERIODS = [7, 30, 90] as const;
const CELL = "px-2 py-1.5 text-left align-top";

function Usage() {
  const t = useDictionary();
  const w = t.security.usage;
  const { format: locale } = useLocale();
  const [days, setDays] = useState<(typeof PERIODS)[number]>(30);
  const usage = useAgentUsage(days);
  const rows = usage.data ?? [];
  return (
    <Card
      title={w.title}
      icon={<Activity className="size-4 text-shell-muted" aria-hidden="true" />}
      action={
        <div className="flex gap-1" role="group" aria-label={w.title}>
          {PERIODS.map((period) => (
            <Button
              key={period}
              type="button"
              size="sm"
              variant={period === days ? "default" : "outline"}
              aria-pressed={period === days}
              onClick={() => setDays(period)}
              data-testid={`agent-usage-days-${period}`}
            >
              {fill(w.days, { count: String(period) })}
            </Button>
          ))}
        </div>
      }
    >
      <p className="mb-2 text-[0.8125rem] text-shell-muted">{w.intro}</p>
      {rows.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-[0.8125rem]" data-testid="agent-usage">
            <thead className="text-xs text-shell-muted">
              <tr>
                <th className={CELL}>{w.agent}</th>
                <th className={`${CELL} text-right`}>{w.runs}</th>
                <th className={`${CELL} text-right`}>{w.succeeded}</th>
                <th className={`${CELL} text-right`}>{w.failed}</th>
                <th className={CELL}>{w.last}</th>
              </tr>
            </thead>
            <tbody className="tabular-nums text-brand-navy">
              {rows.map((row) => (
                <tr key={row.key} className="border-t border-shell-line" data-testid="agent-usage-row" data-key={row.key}>
                  <td className={CELL}>{row.title}</td>
                  <td className={`${CELL} text-right font-semibold`}>{row.runs}</td>
                  <td className={`${CELL} text-right`}>{row.succeeded}</td>
                  <td className={`${CELL} text-right`}>{row.failed}</td>
                  <td className={CELL}>{row.last_at ? exactDate(locale, row.last_at) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : usage.data ? (
        <p className="text-xs text-shell-muted">{w.none}</p>
      ) : null}
    </Card>
  );
}

function Journal() {
  const t = useDictionary();
  const w = t.security.journal;
  const { format: locale } = useLocale();
  const journal = useAgentJournal();
  const rows = (journal.data?.pages ?? []).flat();
  const states = w.states as Record<string, string>;
  return (
    <Card title={w.title} icon={<ListChecks className="size-4 text-shell-muted" aria-hidden="true" />}>
      <p className="mb-2 text-[0.8125rem] text-shell-muted">{w.intro}</p>
      {rows.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-[0.8125rem]" data-testid="agent-journal">
            <thead className="text-xs text-shell-muted">
              <tr>
                <th className={CELL}>{w.when}</th>
                <th className={CELL}>{w.who}</th>
                <th className={CELL}>{w.agent}</th>
                <th className={CELL}>{w.on}</th>
                <th className={CELL}>{w.result}</th>
              </tr>
            </thead>
            <tbody className="text-brand-navy">
              {rows.map((row) => (
                <tr key={row.id} className="border-t border-shell-line" data-testid="agent-journal-row" data-status={row.status}>
                  <td className={`${CELL} whitespace-nowrap tabular-nums`}>{exactDate(locale, row.queued_at)}</td>
                  <td className={CELL}>{row.by_name ?? w.someone}</td>
                  <td className={CELL}>
                    {row.intention_id ? (
                      <Link className="underline" href={`${routes.intention(row.intention_id, "deliverable")}?run=${row.id}`}>
                        {row.title}
                      </Link>
                    ) : (
                      row.title
                    )}
                  </td>
                  <td className={CELL}>
                    {[row.scope, (row.sources ?? []).length ? (row.sources ?? []).join(", ") : w.allSources]
                      .filter(Boolean)
                      .join(" · ")}
                  </td>
                  <td className={CELL}>{states[row.status] ?? row.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : journal.data ? (
        <p className="text-xs text-shell-muted">{w.none}</p>
      ) : null}
      {journal.hasNextPage ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="mt-2"
          disabled={journal.isFetchingNextPage}
          onClick={() => void journal.fetchNextPage()}
          data-testid="agent-journal-more"
        >
          {w.more}
        </Button>
      ) : null}
    </Card>
  );
}

export function AgentUsageTab() {
  return (
    <div className="flex flex-col gap-4" data-testid="agent-usage-tab">
      <Usage />
      <Journal />
    </div>
  );
}
