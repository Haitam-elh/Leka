"use client";

import { Check, Info, User } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { cn } from "cn";

import { usePermissions } from "@/components/shell/shell-provider";
import { PageContainer } from "@/components/shell/page-container";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { useCredits } from "@/lib/billing-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import type { PricedPlan } from "@/lib/subscription";
import { usePayment, usePricing, useSubscription } from "@/lib/subscription-queries";

/**
 * The CORE plans compared (LEKA-466), as Karim's « LEKA CORE SaaS Pricing
 * Plans » lays them out: Free to Enterprise side by side, monthly or yearly,
 * each with what it holds — opened from the plan badge of the header.
 *
 * Every price and quota is the server's (GET /pricing, the catalogue): the
 * yearly discount and the monthly launch offer are two choices, never
 * stacked; the launch offer is said only while it is open and this workspace
 * may still take it. The workspace's plan is marked; who pays for it changes
 * plan — Checkout for a first plan, Stripe's portal once subscribed —, every
 * other member reads. Billing (credits, invoices, payment methods) stays its
 * own page.
 */

type Interval = "month" | "year";
type PlanKey = "free" | "starter" | "growth" | "business" | "enterprise";
const PAYING = new Set(["active", "trialing", "past_due"]);

export function PlansPage() {
  const t = useDictionary();
  const w = t.billing.compare;
  const { format: locale } = useLocale();
  const pricing = usePricing();
  const current = useCredits().data?.plan ?? null;
  const pays = usePermissions()?.includes("workspace:update") ?? false;
  // Read only by who may pay: a member reads the plans, never their checkout.
  const said = useSubscription().data;
  const { checkout, portal } = usePayment();
  const [interval, setInterval] = useState<Interval>("month");

  const money = (cents: number) =>
    new Intl.NumberFormat(locale, {
      style: "currency",
      currency: pricing.data?.currency ?? "EUR",
      minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
    }).format(cents / 100);
  const number = (n: number) => new Intl.NumberFormat(locale).format(n);
  const failed = (error: unknown) =>
    notify.error({ title: error instanceof ApiError ? error.message : w.failed });

  if (pricing.isError) {
    return (
      <PageContainer>
        <ErrorState error={pricing.error} onRetry={() => void pricing.refetch()} />
      </PageContainer>
    );
  }
  const offer = pricing.data;
  const subscribed = said?.status != null && PAYING.has(said.status);
  const launch = offer?.launch_offer;
  const launchOpen = Boolean(launch?.open && said?.launch_offer_available !== false);
  const provisional = (offer?.plans ?? []).some((p) => p.quotas.provisional || p.ai_credits_provisional);

  function price(plan: PricedPlan) {
    if (plan.key === "free") {
      return { big: money(0), sub: w.forever, then: null };
    }
    const quote = plan.quotes.find((q) => q.interval === interval);
    if (!quote) return { big: w.quote, sub: w.quoteSub, then: null };
    const takesLaunch = quote.discount === "launch" && launchOpen;
    const monthly = takesLaunch ? quote.monthly : quote.discount === "launch" ? quote.list_monthly : quote.monthly;
    const then =
      takesLaunch && quote.for_months && quote.then_monthly !== null
        ? fill(w.launchThen, { months: quote.for_months, price: money(quote.then_monthly) })
        : quote.interval === "year"
          ? fill(w.yearTotal, { price: money(quote.charged) })
          : null;
    return { big: money(monthly), sub: w.perMonth, then };
  }

  function features(plan: PricedPlan): { text: string; soon?: boolean; strong?: boolean }[] {
    const q = plan.quotas;
    const key = plan.key as PlanKey;
    const found: { text: string; soon?: boolean; strong?: boolean }[] = [];
    if (q.users) {
      found.push({
        text: q.users > 1 ? fill(w.usersIncluded, { count: number(q.users) }) : fill(w.users, { count: q.users }),
        strong: true,
      });
    }
    if (q.sources) found.push({ text: fill(w.sources, { count: number(q.sources) }) });
    if (q.analyses) found.push({ text: fill(w.analyses, { count: number(q.analyses) }) });
    // Not built yet (Karim, 15/10): said, never announced as working.
    if (q.alert_rules) {
      found.push({
        text: fill(key === "starter" ? w.alertRulesBasic : w.alertRules, { count: number(q.alert_rules) }),
        soon: true,
      });
    }
    if (q.workflows) found.push({ text: fill(w.workflows, { count: number(q.workflows) }), soon: true });
    for (const text of (w.features as Record<PlanKey, readonly string[]>)[key] ?? []) found.push({ text });
    return found;
  }

  function action(plan: PricedPlan) {
    const key = plan.key as PlanKey;
    if (key === current) {
      return (
        <Button type="button" variant="outline" className="w-full" disabled data-testid="plan-current-action">
          {w.currentAction}
        </Button>
      );
    }
    if (key === "enterprise") {
      const href = offer?.booking.url ?? offer?.booking.contact_url ?? "/demo.html";
      return (
        <a
          href={href}
          className="inline-flex h-10 w-full items-center justify-center rounded-lg border border-shell-line text-sm font-semibold text-brand-navy hover:bg-shell-canvas"
          data-testid="plan-contact"
        >
          {w.contact}
        </a>
      );
    }
    if (!pays) return null;
    const busy = checkout.isPending || portal.isPending;
    if (key === "free") {
      // Back to Free: the subscription ended in Stripe's portal, never here.
      return subscribed ? (
        <Button type="button" variant="outline" className="w-full" disabled={busy} onClick={() => portal.mutate(undefined, { onError: failed })} data-testid="plan-choose">
          {w.toFree}
        </Button>
      ) : null;
    }
    const label = fill(w.choose, { plan: plan.name });
    return (
      <Button
        type="button"
        variant={plan.recommended ? "default" : "outline"}
        className="w-full"
        disabled={busy || said?.available === false}
        onClick={() =>
          subscribed
            ? portal.mutate(undefined, { onError: failed })
            : checkout.mutate({ plan: plan.key, interval }, { onError: failed })
        }
        data-testid="plan-choose"
      >
        {label}
      </Button>
    );
  }

  return (
    <PageContainer>
      <div className="mx-auto max-w-3xl text-center">
        <h1 className="text-[1.875rem] leading-tight font-bold tracking-[-0.02em] text-brand-navy md:text-[2.25rem]">
          {w.title}
        </h1>
        <p className="mt-2 text-[1rem] text-shell-accent-muted">{w.subtitle}</p>
      </div>

      <div className="mt-6 flex flex-col items-center gap-2">
        <div
          role="radiogroup"
          aria-label={w.period}
          className="inline-flex rounded-xl border border-shell-line bg-shell-canvas p-1"
        >
          {(["month", "year"] as const).map((each) => (
            <button
              key={each}
              type="button"
              role="radio"
              aria-checked={interval === each}
              onClick={() => setInterval(each)}
              data-testid={`plans-${each}`}
              className={cn(
                "rounded-lg px-5 py-2 text-sm font-medium outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
                interval === each ? "bg-brand-violet text-white" : "text-shell-muted hover:text-brand-navy",
              )}
            >
              {each === "month"
                ? w.monthly
                : fill(w.yearly, { percent: offer?.annual_discount_percent ?? 0 })}
            </button>
          ))}
        </div>
        {launch && launchOpen && interval === "month" ? (
          <p className="text-[0.8125rem] text-shell-muted" data-testid="plans-launch">
            {fill(w.launch, { percent: launch.percent, months: launch.months })}
          </p>
        ) : null}
      </div>

      {offer === undefined ? (
        <div className="mt-6 h-96 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />
      ) : (
        <ul className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-5" data-testid="plans">
          {offer.plans.map((plan) => {
            const shown = price(plan);
            const key = plan.key as PlanKey;
            const mine = key === current;
            return (
              <li
                key={plan.key}
                data-testid="plan-card"
                data-plan={plan.key}
                data-current={mine}
                className={cn(
                  "relative flex flex-col rounded-2xl border bg-white p-5",
                  mine
                    ? "border-2 border-brand-navy"
                    : plan.recommended
                      ? "border-2 border-brand-violet"
                      : "border-shell-line",
                )}
              >
                {mine || plan.recommended ? (
                  <span
                    className={cn(
                      "absolute -top-3 left-1/2 -translate-x-1/2 rounded-full px-3 py-1 text-xs font-semibold text-white",
                      mine ? "bg-brand-navy" : "bg-brand-violet",
                    )}
                  >
                    {mine ? w.current : w.recommended}
                  </span>
                ) : null}
                <h2 className="text-[1.375rem] font-bold text-brand-navy">{plan.name}</h2>
                <p className="mt-1 min-h-10 text-[0.9375rem] text-shell-muted">
                  {(w.taglines as Record<PlanKey, string>)[key]}
                </p>
                <p className="mt-4 text-[2rem] leading-none font-bold text-brand-navy tabular-nums" data-testid="plan-price">
                  {shown.big}
                </p>
                <p className="mt-1 text-[0.8125rem] text-shell-muted">{shown.sub}</p>
                {shown.then ? (
                  <p className="mt-1 text-xs text-shell-muted" data-testid="plan-then">
                    {shown.then}
                  </p>
                ) : null}
                <hr className="my-4 border-shell-line" />
                <ul className="flex flex-1 flex-col gap-2 text-[0.875rem] text-brand-navy">
                  {features(plan).map((f) => (
                    <li key={f.text} className="flex items-start gap-2">
                      {f.strong ? (
                        <User className="mt-0.5 size-4 shrink-0 text-shell-muted" aria-hidden="true" />
                      ) : (
                        <Check className="mt-0.5 size-4 shrink-0 text-brand-violet" aria-hidden="true" />
                      )}
                      <span className={cn(f.strong && "font-semibold")}>
                        {f.text}
                        {f.soon ? <span className="ms-1 text-xs text-shell-muted">({w.soon})</span> : null}
                      </span>
                    </li>
                  ))}
                </ul>
                <div className="mt-5">{action(plan)}</div>
                <p className="mt-3 text-center text-xs text-shell-muted">
                  {(w.audiences as Record<PlanKey, string>)[key]}
                </p>
              </li>
            );
          })}
        </ul>
      )}

      {!pays ? <p className="mt-4 text-center text-[0.8125rem] text-shell-muted">{w.askAdmin}</p> : null}

      <div className="mt-6 flex items-start gap-3 rounded-xl bg-shell-canvas px-4 py-3 text-[0.875rem] text-brand-navy">
        <Info className="mt-0.5 size-5 shrink-0 text-brand-violet" aria-hidden="true" />
        <p>{w.note}</p>
      </div>
      <p className="mt-3 text-center text-xs text-shell-muted">
        {w.terms}
        {provisional ? ` ${w.provisional}` : ""}
      </p>
      {pays ? (
        <p className="mt-2 text-center text-[0.8125rem]">
          <Link href={routes.billing()} className="text-shell-nav-active hover:underline">
            {w.billingLink}
          </Link>
        </p>
      ) : null}
    </PageContainer>
  );
}
