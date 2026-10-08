"use client";

import { Bot, Database, Headset, Layers, Play, ReceiptText, Users, Waypoints, Workflow } from "lucide-react";

import { IconTile } from "@/components/environment/parts";
import { PageContainer } from "@/components/shell/page-container";
import { ErrorState } from "@/components/states/error-state";
import { useWorkspaceUsage } from "@/lib/billing-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";

/**
 * Facturation, laid out as docs/product/mockups/16-facturation.jpeg with
 * what is real: no paid plan, payment nor invoice exists on a workspace
 * yet — said so — and the consumption, counted (GET /billing/usage): who
 * is in, what is connected, the model's size, this month's intentions,
 * analyses, capability runs and plans, against last month.
 */
export function BillingScreen() {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.billing;
  const usage = useWorkspaceUsage();
  const data = usage.data;
  const number = new Intl.NumberFormat(locale === "fr" ? "fr-FR" : "en-GB");

  return (
    <PageContainer>
      <div className="mb-5">
        <h1 className="text-[2.125rem] leading-tight font-bold tracking-[-0.02em] text-brand-navy">{w.title}</h1>
        <p className="mt-1 text-[1.0625rem] text-shell-accent-muted">{w.subtitle}</p>
      </div>
      {usage.isError ? (
        <ErrorState error={usage.error} onRetry={() => void usage.refetch()} />
      ) : !data ? (
        <div className="h-96 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />
      ) : (
        <div className="flex flex-col gap-4" data-testid="billing">
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            {[
              { key: "plan", icon: ReceiptText, tone: "violet" as const, value: w.planNone, label: w.plan, foot: w.planNoneFoot, small: true },
              { key: "members", icon: Users, tone: "violet" as const, value: number.format(data.members), label: w.members, foot: null },
              {
                key: "sources",
                icon: Waypoints,
                tone: "info" as const,
                value: number.format(data.sources_connected),
                label: w.sources,
                foot: fill(w.sourcesFoot, { total: data.sources }),
              },
              { key: "entities", icon: Database, tone: "success" as const, value: number.format(data.entities), label: w.entities, foot: null },
            ].map((tile) => (
              <div key={tile.key} className="flex items-start gap-3 rounded-xl border border-shell-line bg-white p-4" data-testid={`billing-${tile.key}`}>
                <IconTile icon={tile.icon} tone={tile.tone} />
                <div className="min-w-0">
                  <p className="text-[0.8125rem] text-shell-muted">{tile.label}</p>
                  <p className={tile.small ? "text-[1rem] font-semibold text-brand-navy" : "text-[1.5rem] leading-tight font-bold text-brand-navy tabular-nums"}>
                    {tile.value}
                  </p>
                  {tile.foot ? <p className="text-xs text-shell-muted">{tile.foot}</p> : null}
                </div>
              </div>
            ))}
          </div>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
            <section className="rounded-xl border border-shell-line bg-white p-4" data-testid="billing-month">
              <h2 className="font-semibold text-brand-navy">{w.month}</h2>
              <p className="mb-3 text-xs text-shell-muted">
                {fill(w.since, {
                  date: new Intl.DateTimeFormat(locale === "fr" ? "fr-FR" : "en-GB", { dateStyle: "long" }).format(new Date(data.month_start)),
                })}
              </p>
              <ul className="space-y-3">
                {(
                  [
                    ["intentions", Layers, data.intentions, data.previous.intentions],
                    ["analyses", Workflow, data.analyses, data.previous.analyses],
                    ["capability_runs", Play, data.capability_runs, data.previous.capability_runs],
                    ["plans", Bot, data.plans, undefined],
                  ] as const
                ).map(([key, Icon, value, previous]) => (
                  <li key={key} className="flex items-center gap-3 text-[0.875rem]" data-testid={`billing-row-${key}`}>
                    <Icon className="size-4 text-shell-nav-active" aria-hidden="true" />
                    <span className="flex-1 text-brand-navy">{w.rows[key]}</span>
                    <span className="font-semibold text-brand-navy tabular-nums">{number.format(value)}</span>
                    {previous !== undefined ? (
                      <span className="w-36 text-right text-xs text-shell-muted">{fill(w.versus, { count: previous })}</span>
                    ) : (
                      <span className="w-36" />
                    )}
                  </li>
                ))}
              </ul>
            </section>
            <section className="rounded-xl border border-shell-line bg-white p-4" data-testid="billing-invoices">
              <h2 className="mb-2 font-semibold text-brand-navy">{w.invoices}</h2>
              <p className="text-[0.8125rem] text-shell-muted">{w.invoicesNone}</p>
            </section>
          </div>
          <section className="flex flex-wrap items-center gap-4 rounded-xl bg-brand-violet-soft/60 px-5 py-4">
            <Headset className="size-6 shrink-0 text-shell-nav-active" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="font-semibold text-brand-navy">{w.questionTitle}</p>
              <p className="text-[0.8125rem] text-shell-muted">{w.questionBody}</p>
            </div>
          </section>
        </div>
      )}
    </PageContainer>
  );
}
