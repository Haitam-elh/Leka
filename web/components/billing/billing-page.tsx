"use client";

import { Bot, Database, Layers, Play, ReceiptText, Sparkles, Users, Waypoints, Workflow } from "lucide-react";
import { usePathname } from "next/navigation";

import { IconTile, TILE_TONES } from "@/components/environment/parts";
import { AddOnSubscriptions } from "@/components/billing/add-on-subscriptions";
import { ContractScreen } from "@/components/billing/contract-page";
import { SubscriptionSection } from "@/components/billing/subscription-section";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { StatCard, StatGrid } from "@/components/shell/stat-card";
import { ErrorState } from "@/components/states/error-state";
import type { Credits } from "@/lib/billing";
import { useCredits, useWorkspaceUsage } from "@/lib/billing-queries";
import { ENTERPRISE } from "@/lib/contract";
import { fill } from "@/lib/i18n/dictionaries";
import { buildBreadcrumb } from "@/lib/navigation/breadcrumb";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { useSubscription } from "@/lib/subscription-queries";

/**
 * Facturation, laid out as docs/product/mockups/16-facturation.jpeg with
 * what is real: the workspace's plan and its AI credits this month (GET
 * /billing/credits, LEKA-430) — used, left, and what to do once they are
 * spent; no payment nor invoice yet — said so — and the consumption,
 * counted (GET /billing/usage): who is in, what is connected, the model's
 * size, this month's intentions, analyses, capability runs and plans,
 * against last month.
 */
export function BillingScreen() {
  const t = useDictionary();
  const pathname = usePathname();
  const { format: locale } = useLocale();
  const w = t.billing;
  // Paying through Stripe: its invoices are Stripe's, not « attribuée par votre interlocuteur ».
  const stripe = useSubscription().data?.has_customer ?? false;
  const usage = useWorkspaceUsage();
  const credits = useCredits().data;
  const data = usage.data;
  const number = new Intl.NumberFormat(locale);
  const day = (iso: string) =>
    new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(new Date(iso));

  // Under an Enterprise contract (2026-10-25): « Contrat », never a bill.
  if (credits?.plan === ENTERPRISE) return <ContractScreen />;
  return (
    <PageContainer>
      <PageHeader title={w.title} subtitle={w.subtitle} breadcrumb={buildBreadcrumb(pathname, t)} />
      {usage.isError ? (
        <ErrorState error={usage.error} onRetry={() => void usage.refetch()} />
      ) : !data ? (
        <div className="h-96 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />
      ) : (
        <div className="flex flex-col gap-4" data-testid="billing">
          <StatGrid count={4}>
            {[
              {
                key: "plan",
                icon: ReceiptText,
                tone: "violet" as const,
                value: credits ? w.plans[credits.plan] : "-",
                label: w.plan,
                foot: credits ? (credits.plan_since ? fill(w.planSince, { date: day(credits.plan_since) }) : w.planDefault) : null,
              },
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
              <StatCard
                key={tile.key}
                icon={tile.icon}
                tone={tile.tone}
                value={tile.value}
                label={tile.label}
                foot={tile.foot}
                testId={`billing-${tile.key}`}
              />
            ))}
          </StatGrid>
          {credits ? <CreditsSection credits={credits} number={number} day={day} /> : null}
          <SubscriptionSection />
          <AddOnSubscriptions />
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
            <section className="rounded-xl border border-shell-line bg-white p-4" data-testid="billing-month">
              <h2 className="font-semibold text-brand-navy">{w.month}</h2>
              <p className="mb-3 text-xs text-shell-muted">
                {fill(w.since, {
                  date: new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(new Date(data.month_start)),
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
                      <span className="w-36 text-end text-xs text-shell-muted">{fill(w.versus, { count: previous })}</span>
                    ) : (
                      <span className="w-36" />
                    )}
                  </li>
                ))}
              </ul>
            </section>
            <section className="rounded-xl border border-shell-line bg-white p-4" data-testid="billing-invoices">
              <h2 className="mb-2 font-semibold text-brand-navy">{w.invoices}</h2>
              <p className="text-[0.8125rem] text-shell-muted">{stripe ? w.invoicesStripe : w.invoicesNone}</p>
            </section>
          </div>
        </div>
      )}
    </PageContainer>
  );
}

const BAR = { ok: "bg-shell-nav-active", warning: "bg-state-warning", exhausted: "bg-state-danger" } as const;

/** Its AI credits this month: used of the allowance, what is left until when, and — near or past the limit — what to do. */
function CreditsSection({
  credits,
  number,
  day,
}: {
  credits: Credits;
  number: Intl.NumberFormat;
  day: (iso: string) => string;
}) {
  const w = useDictionary().billing;
  const c = w.credits;
  const end = day(credits.period_end);
  const shown = Math.min(100, Math.max(0, credits.percent));
  return (
    <section className="rounded-xl border border-shell-line bg-white p-4" data-testid="billing-credits">
      <div className="flex flex-wrap items-start gap-3">
        <IconTile icon={Sparkles} tone={credits.state === "exhausted" ? "danger" : credits.state === "warning" ? "warning" : "violet"} />
        <div className="min-w-0 flex-1">
          <h2 className="font-semibold text-brand-navy">{c.title}</h2>
          <p className="text-xs text-shell-muted">{c.explain}</p>
        </div>
        <p className="text-[1.5rem] leading-tight font-bold text-brand-navy tabular-nums" data-testid="billing-credits-used">
          {fill(c.used, { used: number.format(Math.round(credits.used)), allowance: number.format(credits.allowance) })}
        </p>
      </div>
      <div
        className="mt-3 h-2 overflow-hidden rounded-full bg-shell-canvas"
        role="progressbar"
        aria-label={c.title}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(shown)}
      >
        <div className={`h-full rounded-full ${BAR[credits.state]}`} style={{ width: `${shown}%` }} />
      </div>
      <p className="mt-2 text-xs text-shell-muted" data-testid="billing-credits-remaining">
        {fill(c.remaining, { remaining: number.format(Math.floor(credits.remaining)), date: end })}
        {credits.packs > 0 ? ` · ${fill(c.packs, { packs: number.format(credits.packs) })}` : null}
      </p>
      {credits.state !== "ok" ? (
        <div
          className={`mt-3 rounded-lg px-3 py-2 text-[0.8125rem] ${credits.state === "exhausted" ? TILE_TONES.danger : TILE_TONES.warning}`}
          role="status"
          data-testid="billing-credits-state"
        >
          <p className="font-semibold">
            {credits.state === "exhausted" ? (credits.enforced ? fill(c.exhausted, { date: end }) : c.exhaustedSoft) : c.warning}
          </p>
          <p>{c.how}</p>
        </div>
      ) : null}
    </section>
  );
}
