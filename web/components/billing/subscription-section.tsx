"use client";

import { CreditCard, ExternalLink } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { IconTile, TILE_TONES } from "@/components/environment/parts";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import type { PricedPlan } from "@/lib/subscription";
import { usePayment, usePricing, useSubscription } from "@/lib/subscription-queries";

/**
 * Votre formule (LEKA-431): the plan the workspace pays for, as Stripe last
 * said it, and how to change it — Stripe Checkout for a first plan, at the
 * price the pricing page shows (GET /pricing, the one source of prices);
 * Stripe's portal once subscribed (card, invoices, plan, cancellation).
 * The plan itself changes only when Stripe confirms the payment.
 */

const PAYING = new Set(["active", "trialing", "past_due"]);
type Interval = "month" | "year";

export function SubscriptionSection() {
  const t = useDictionary();
  const w = t.billing.subscription;
  const { locale } = useLocale();
  const params = useSearchParams();
  const said = useSubscription().data;
  const pricing = usePricing().data;
  const { checkout, portal } = usePayment();
  const [interval, setInterval] = useState<Interval>("month");
  const money = (cents: number) =>
    new Intl.NumberFormat(locale === "fr" ? "fr-FR" : "en-GB", {
      style: "currency",
      currency: pricing?.currency ?? "EUR",
      minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
    }).format(cents / 100);
  const day = (iso: string) =>
    new Intl.DateTimeFormat(locale === "fr" ? "fr-FR" : "en-GB", { dateStyle: "long" }).format(new Date(iso));

  if (!said) return null;
  const back = params.get("checkout");
  const subscribed = said.status !== null && PAYING.has(said.status);

  function failed(error: unknown) {
    notify.error({ title: error instanceof ApiError ? error.message : w.failed });
  }

  function price(plan: PricedPlan) {
    const quote = plan.quotes.find((q) => q.interval === interval);
    if (!quote) return null;
    // The launch offer only where this workspace may still take it.
    const launch = quote.discount === "launch" && said?.launch_offer_available;
    const monthly = launch ? quote.monthly : quote.discount === "launch" ? quote.list_monthly : quote.monthly;
    return (
      <p className="text-[0.8125rem] text-shell-muted">
        <span className="text-[1.25rem] font-bold text-brand-navy tabular-nums">{money(monthly)}</span> {w.perMonth}
        {launch && quote.for_months && quote.then_monthly !== null
          ? ` · ${fill(w.launch, { months: quote.for_months, price: money(quote.then_monthly) })}`
          : null}
        {quote.interval === "year" ? ` · ${fill(w.yearly, { price: money(quote.charged) })}` : null}
      </p>
    );
  }

  return (
    <section className="rounded-xl border border-shell-line bg-white p-4" data-testid="billing-subscription">
      <div className="mb-3 flex items-center gap-3">
        <IconTile icon={CreditCard} tone="violet" />
        <h2 className="font-semibold text-brand-navy">{w.title}</h2>
      </div>
      {back === "success" ? (
        <p className={`mb-3 rounded-lg px-3 py-2 text-[0.8125rem] ${TILE_TONES.success}`} role="status" data-testid="billing-checkout-back">
          {w.success}
        </p>
      ) : back === "cancelled" ? (
        <p className={`mb-3 rounded-lg px-3 py-2 text-[0.8125rem] ${TILE_TONES.neutral}`} role="status" data-testid="billing-checkout-back">
          {w.cancelled}
        </p>
      ) : null}
      {!said.available ? (
        <p className="text-[0.8125rem] text-shell-muted" data-testid="billing-not-available">
          {w.notAvailable}{" "}
          <a className="underline" href="/tarifs.html">
            {w.seePricing}
          </a>
        </p>
      ) : subscribed ? (
        <div className="flex flex-col gap-2" data-testid="billing-subscribed">
          <p className="text-[0.875rem] text-brand-navy">
            {fill(w.current, {
              plan: (t.billing.plans as Record<string, string>)[said.plan] ?? said.plan,
              interval: said.interval === "year" ? w.yearlyWord : w.monthlyWord,
            })}
          </p>
          {said.current_period_end ? (
            <p className="text-xs text-shell-muted">
              {fill(said.cancel_at_period_end ? w.endsOn : w.renewsOn, { date: day(said.current_period_end) })}
            </p>
          ) : null}
          {said.status === "past_due" ? (
            <p className={`rounded-lg px-3 py-2 text-[0.8125rem] ${TILE_TONES.warning}`} role="alert">
              {w.pastDue}
            </p>
          ) : null}
          <div>
            <Button type="button" variant="outline" disabled={portal.isPending} onClick={() => portal.mutate(undefined, { onError: failed })}>
              <ExternalLink className="size-4" aria-hidden="true" />
              {w.manage}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3" data-testid="billing-plans">
          <div className="flex gap-1" role="radiogroup" aria-label={w.billingLabel}>
            {(["month", "year"] as const).map((each) => (
              <button
                key={each}
                type="button"
                role="radio"
                aria-checked={interval === each}
                onClick={() => setInterval(each)}
                className={`rounded-full px-3 py-1 text-[0.8125rem] font-medium ${interval === each ? "bg-brand-navy text-white" : "bg-shell-canvas text-shell-muted"}`}
              >
                {each === "month" ? w.monthlyWord : fill(w.yearlyChoice, { percent: pricing?.annual_discount_percent ?? 20 })}
              </button>
            ))}
          </div>
          <ul className="grid gap-3 md:grid-cols-3">
            {(pricing?.plans ?? [])
              .filter((plan) => plan.self_service && plan.quotes.length && plan.key !== "free")
              .map((plan) => (
                <li
                  key={plan.key}
                  className={`flex flex-col gap-2 rounded-lg border p-3 ${plan.recommended ? "border-shell-nav-active" : "border-shell-line"}`}
                  data-testid="billing-plan"
                  data-plan={plan.key}
                >
                  <p className="font-semibold text-brand-navy">{plan.name}</p>
                  {price(plan)}
                  {plan.ai_credits_per_month !== null ? (
                    <p className="text-xs text-shell-muted">{fill(w.credits, { n: plan.ai_credits_per_month })}</p>
                  ) : null}
                  <Button
                    type="button"
                    variant={plan.recommended ? "default" : "outline"}
                    disabled={checkout.isPending}
                    onClick={() => checkout.mutate({ plan: plan.key, interval }, { onError: failed })}
                  >
                    {fill(w.choose, { plan: plan.name })}
                  </Button>
                </li>
              ))}
          </ul>
          <p className="text-xs text-shell-muted">{w.terms}</p>
        </div>
      )}
    </section>
  );
}
