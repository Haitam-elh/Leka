"use client";

import { Gauge } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "cn";

import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import type { CreditPlan, CreditPrompt as Prompt } from "@/lib/billing";
import { useAskUpgrade, useCreditPrompt, useCreditPromptDismiss } from "@/lib/billing-queries";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

/**
 * The AI capacity's prompt (LEKA-527): past 90 % and 100 % of the month's
 * AI credits, a banner at the top of the page, under what stays pinned:
 * never over what is being read, never in the way of an intention running.
 *
 * Where the workspace stands (used of its allowance, the bar said in words
 * as well as in colour), what happens next (at 100 %, the actual policy:
 * LEKA's AI paused until the credits come back, or nothing blocked), what
 * AI credits are and where their use is detailed. Then the plan that gives
 * more, as the server reads it from the catalogue: its credits, its price
 * on the subscription's own cadence, what it adds to the current one. Who
 * may pay opens that plan on the plans page, the one place it is bought,
 * and is told the credits come once the payment is confirmed; who may not
 * asks the admins, once. Above the plans sold, LEKA's sales; under a
 * contract, the day the credits come back and whom to ask.
 *
 * « Plus tard » (90 %) or « Fermer » (100 %) puts that threshold aside for
 * the reader, this month: the 100 % one still comes.
 */

export function CreditPrompt() {
  const t = useDictionary();
  const w = t.billing.prompt;
  const { format: locale } = useLocale();
  const pathname = usePathname();
  const prompt = useCreditPrompt();
  const dismiss = useCreditPromptDismiss();
  const ask = useAskUpgrade();
  const found = prompt.data;
  // On the plans page, the plans are what is on screen already.
  if (!found || pathname === routes.billingPlans()) return null;

  const spent = found.threshold >= 100;
  const number = new Intl.NumberFormat(locale);
  const day = new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(new Date(found.period_end));
  const percent = Math.floor(found.percent);
  const shown = Math.min(100, Math.max(0, found.percent));
  const money = (cents: number) =>
    new Intl.NumberFormat(locale, {
      style: "currency",
      currency: found.currency,
      minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
    }).format(cents / 100);
  const title = spent
    ? w.spent
    : fill(w.near, { left: Math.max(1, Math.ceil(100 - found.percent)) });
  // What happens next, as the quota's policy is: paused, or nothing blocked.
  const impact = spent
    ? found.enforced
      ? fill(w.paused, { date: day })
      : w.open
    : found.enforced
      ? fill(w.nearPaused, { date: day })
      : null;
  const threshold = found.threshold;

  async function putAside() {
    try {
      await dismiss.mutateAsync(threshold);
    } catch {
      notify.error({ title: w.failed });
    }
  }

  async function askAdmins() {
    try {
      await ask.mutateAsync(threshold);
    } catch {
      notify.error({ title: w.failed });
    }
  }

  return (
    <section
      aria-label={title}
      data-testid="credit-prompt"
      data-threshold={found.threshold}
      data-path={found.path}
      className={cn(
        "border-b px-4 py-3 text-[0.8125rem] text-brand-navy sm:px-6 lg:px-8",
        spent ? "border-state-danger/25 bg-state-danger-soft" : "border-state-warning/25 bg-state-warning-soft",
      )}
    >
      <div className="flex flex-wrap items-start gap-x-4 gap-y-3">
        <Gauge
          className={cn("mt-0.5 size-4 shrink-0", spent ? "text-state-danger" : "text-state-warning")}
          aria-hidden="true"
        />
        <div className="flex min-w-0 flex-1 basis-80 flex-col gap-1.5">
          <p className="text-[0.875rem] font-semibold" data-testid="credit-prompt-title">
            {title}
          </p>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <p className="tabular-nums" data-testid="credit-prompt-usage">
              {fill(w.usage, {
                used: number.format(Math.round(found.used)),
                allowance: number.format(found.allowance),
                percent,
              })}{" "}
              {spent
                ? fill(w.back, { date: day })
                : fill(w.remaining, { remaining: number.format(Math.floor(found.remaining)), date: day })}
            </p>
            <div
              className="h-1.5 w-32 overflow-hidden rounded-full bg-white/70"
              role="progressbar"
              aria-label={t.billing.credits.title}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(shown)}
              aria-valuetext={fill(w.bar, { percent })}
            >
              <div
                className={cn("h-full rounded-full", spent ? "bg-state-danger" : "bg-state-warning")}
                style={{ width: `${shown}%` }}
              />
            </div>
          </div>
          {impact ? <p data-testid="credit-prompt-impact">{impact}</p> : null}
          <Offer found={found} money={money} number={number} day={day} />
          <p className="text-shell-muted">
            {w.what}{" "}
            <Link href={routes.billing()} className="font-medium text-shell-nav-active hover:underline">
              {w.detail}
            </Link>
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Primary found={found} onAsk={() => void askAdmins()} asking={ask.isPending} />
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={dismiss.isPending}
            onClick={() => void putAside()}
            data-testid="credit-prompt-dismiss"
          >
            {spent ? w.close : w.later}
          </Button>
        </div>
      </div>
    </section>
  );
}

/** The plan that gives more: its credits and price, and what it adds — or,
 * under a contract, when the credits come back. */
function Offer({
  found,
  money,
  number,
  day,
}: {
  found: Prompt;
  money: (cents: number) => string;
  number: Intl.NumberFormat;
  day: string;
}) {
  const w = useDictionary().billing.prompt;
  const next = found.recommended;
  if (found.path === "contract" || !next) {
    return <p data-testid="credit-prompt-offer">{fill(found.can_pay ? w.contract : w.contractAsk, { date: day })}</p>;
  }
  const price = priceOf(next, money, w);
  const more = [
    found.more_credits ? fill(w.moreCredits, { credits: number.format(found.more_credits) }) : null,
    found.more_monthly ? fill(w.morePrice, { price: money(found.more_monthly) }) : null,
  ].filter(Boolean);
  return (
    <div data-testid="credit-prompt-offer" className="flex flex-col gap-0.5">
      <p>
        <span className="font-semibold">{next.name}</span>
        {" · "}
        {next.credits != null ? fill(w.credits, { credits: number.format(next.credits) }) : w.quote}
        {price ? ` · ${price}` : null}
      </p>
      {more.length ? <p>{fill(w.versus, { plan: found.current.name, more: more.join(", ") })}</p> : null}
      {found.path === "upgrade" && found.can_pay ? <p className="text-shell-muted">{w.notYet}</p> : null}
      {!found.can_pay && !found.asked ? <p className="text-shell-muted">{w.askNote}</p> : null}
    </div>
  );
}

/** A plan's price as it would be billed: the launch offer's months and
 * after, the year's total, or the month's. */
function priceOf(
  plan: CreditPlan,
  money: (cents: number) => string,
  w: Dictionary["billing"]["prompt"],
): string | null {
  if (plan.monthly == null) return null;
  if (plan.discount === "launch" && plan.for_months && plan.list_monthly != null) {
    return fill(w.priceLaunch, {
      price: money(plan.monthly),
      months: plan.for_months,
      then: money(plan.list_monthly),
    });
  }
  if (plan.interval === "year" && plan.charged != null) {
    return fill(w.priceYear, { price: money(plan.monthly), total: money(plan.charged) });
  }
  return fill(w.priceMonth, { price: money(plan.monthly) });
}

/** What the reader can do about it: open the plan, reach LEKA's sales, or
 * ask the admins, said once asked. */
function Primary({ found, onAsk, asking }: { found: Prompt; onAsk: () => void; asking: boolean }) {
  const w = useDictionary().billing.prompt;
  const next = found.recommended;
  if (!found.can_pay) {
    return found.asked ? (
      <p role="status" className="font-medium" data-testid="credit-prompt-asked">
        {w.asked}
      </p>
    ) : (
      <Button type="button" size="sm" disabled={asking} onClick={onAsk} data-testid="credit-prompt-ask">
        {w.ask}
      </Button>
    );
  }
  if (found.path === "upgrade" && next) {
    const query = new URLSearchParams({ plan: next.key, ...(next.interval ? { interval: next.interval } : {}) });
    return (
      <Link
        href={`${routes.billingPlans()}?${query}`}
        className={buttonVariants({ size: "sm" })}
        data-testid="credit-prompt-upgrade"
      >
        {fill(w.see, { plan: next.name })}
      </Link>
    );
  }
  return (
    <a
      href={found.contact_url}
      target="_blank"
      rel="noreferrer"
      className={buttonVariants({ size: "sm" })}
      data-testid="credit-prompt-contact"
    >
      {w.contact}
    </a>
  );
}
