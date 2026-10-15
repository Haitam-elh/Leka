"use client";

import { ArrowRight, Gauge, Route } from "lucide-react";
import Link from "next/link";

import { cn } from "cn";

import { titleOf } from "@/components/capabilities/catalogue";
import { Card } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { useConfirm } from "@/components/interactions/confirm";
import { exactDate } from "@/components/knowledge/time";
import { usePermissions } from "@/components/shell/shell-provider";
import { sourceTitle } from "@/components/sources/source-logo";
import type { SourceKind } from "@/lib/sources";
import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { Feasibility, PathStep } from "@/lib/intentions/api";
import { useIntentionFeasibility } from "@/lib/intentions/queries";
import { useAddOns, useBuy } from "@/lib/billing-queries";
import { notify } from "@/lib/notify";
import { usePayment } from "@/lib/subscription-queries";

/**
 * What it takes to carry an intention through here (LEKA-439): the
 * capabilities it needs — each included, in beta (usable, its future price
 * said), an add-on or planned, usable here or not — the AI credits left and
 * what it should cost; then the verdict and the least it takes, cheapest
 * first: what to connect or allow, or the cheapest plan that is enough.
 * Never a promise the plan or the credits would break: what cannot run is
 * said so. Nothing is bought here without a yes: changing plan, an agent
 * or a bundle asks first, says in full what is paid — the price excl. VAT,
 * the launch offer and what it renews at, monthly, the agents a plan
 * includes (LEKA-462) — then opens the secure payment page; and only
 * someone who may pay for the workspace sees the button.
 */

/** A source kind's name — its own word when LEKA has no mark for it. */
function sourceNameOf(kind: string): string {
  try {
    return sourceTitle(kind as SourceKind);
  } catch {
    return kind;
  }
}

const OFFER_TONES = { included: "success", beta: "violet", add_on: "warning", planned: "neutral" } as const;

export function FeasibilityPanel({
  feasibility,
  intentionId,
}: {
  feasibility: Feasibility;
  intentionId?: string;
}) {
  const t = useDictionary();
  const w = t.intentions.feasibility;
  const { format: locale } = useLocale();
  const shown = feasibility.needed.filter((n) => n.selected || n.essential || !n.available);
  const credits = feasibility.credits;
  const number = (value: number) => new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value);
  return (
    <Card
      title={w.title}
      icon={<Route className="size-4 text-shell-muted" aria-hidden="true" />}
    >
      <div className="flex flex-col gap-3" data-testid="feasibility" data-verdict={feasibility.verdict}>
        <p
          className={cn(
            "text-[0.875rem] font-medium",
            feasibility.verdict === "ready" ? "text-state-success" : "text-brand-navy",
          )}
          data-testid="feasibility-verdict"
        >
          {w.verdicts[feasibility.verdict]}
        </p>
        {feasibility.path.length ? (
          <ol className="flex flex-col gap-2" data-testid="feasibility-path">
            {feasibility.path.map((step, index) => (
              <StepItem key={`${step.kind}-${index}`} step={step} intentionId={intentionId} />
            ))}
          </ol>
        ) : null}
        <ul className="divide-y divide-shell-line/70" data-testid="feasibility-needed">
          {shown.map((n) => (
            <li
              key={n.key}
              className="flex flex-wrap items-center gap-x-2 gap-y-1 py-2 text-[0.8125rem]"
              data-testid="feasibility-capability"
              data-key={n.key}
              data-offer={n.offer}
            >
              <span className="min-w-0 flex-1 font-medium text-brand-navy">
                {titleOf(t, { key: n.key, title: n.title, kind: n.kind as never })}
              </span>
              <Pill tone={OFFER_TONES[n.offer]}>{w.offers[n.offer]}</Pill>
              <Pill tone={n.available ? "success" : "warning"}>
                {n.available ? (n.essential ? w.available : w.always) : w.unavailable}
              </Pill>
            </li>
          ))}
        </ul>
        <div className="flex items-start gap-2 rounded-lg bg-shell-canvas px-3 py-2 text-[0.8125rem]" data-testid="feasibility-credits">
          <Gauge className="mt-0.5 size-4 shrink-0 text-shell-muted" aria-hidden="true" />
          <div className="min-w-0 text-brand-navy">
            <p>
              {fill(w.credits, {
                remaining: number(credits.remaining),
                allowance: number(credits.allowance),
                plan: w.plans[credits.plan],
              })}
            </p>
            <p className="text-shell-muted">
              {feasibility.estimate !== null && feasibility.estimate !== undefined
                ? fill(w.estimate, { credits: number(Math.max(1, feasibility.estimate)) })
                : w.unknownCost}
            </p>
            {credits.enforced ? (
              <p className="text-xs text-shell-muted">
                {fill(w.enforced, { date: exactDate(locale, credits.period_end) })}
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </Card>
  );
}

function StepItem({ step, intentionId }: { step: PathStep; intentionId?: string }) {
  const t = useDictionary();
  const w = t.intentions.feasibility;
  const { format: locale } = useLocale();
  const confirm = useConfirm();
  const { checkout } = usePayment();
  const buy = useBuy();
  const sold = useAddOns().data;
  const permissions = usePermissions() ?? [];
  const pays = permissions.includes("workspace:update");
  const detail = step.detail as Record<string, unknown>;
  const money = (cents: unknown) =>
    typeof cents === "number"
      ? new Intl.NumberFormat(locale, { style: "currency", currency: "EUR" }).format(cents / 100)
      : w.priceUnknown;
  const plan = typeof detail.plan === "string" ? detail.plan : "";
  const planName = (w.plans as Record<string, string>)[plan] ?? plan;
  const sources = Array.isArray(detail.sources)
    ? detail.sources.map((kind) => sourceNameOf(String(kind))).join(t.catalogue.or)
    : "";
  const agentName = (key: unknown) =>
    sold?.agents.find((a) => a.key === key)?.title ?? String(key ?? "");
  const found = sold?.bundles.find((b) => b.key === detail.bundle);
  const bundleName = found
    ? locale.startsWith("en")
      ? found.name.en
      : found.name.fr
    : String(detail.bundle ?? "");
  const said = fill((w.steps as Record<string, string>)[step.kind] ?? step.kind, {
    sources,
    capability: String(detail.capability ?? ""),
    credits: String(detail.credits ?? ""),
    price: money(detail.price ?? detail.monthly_price),
    agent: agentName(detail.agent),
    bundle: bundleName,
    plan: planName,
  });

  async function changePlan() {
    const launch =
      typeof detail.launch_percent === "number"
        ? ` ${fill(w.launch, {
            percent: String(detail.launch_percent),
            months: String(detail.launch_months ?? ""),
            launchPrice: money(detail.launch_price),
            price: money(detail.then_price ?? detail.monthly_price),
          })}`
        : "";
    const includes = Array.isArray(detail.includes) && detail.includes.length
      ? ` ${fill(w.includesAgents, { agents: detail.includes.map(agentName).join(", ") })}`
      : "";
    const ok = await confirm({
      title: fill(w.confirmTitle, { plan: planName }),
      description:
        fill(w.confirmBody, {
          price: money(detail.monthly_price),
          credits: String(detail.credits ?? ""),
        }) +
        launch +
        includes +
        (detail.renews ? ` ${w.renews}` : ""),
      confirmLabel: w.confirm,
    });
    if (!ok) return;
    checkout.mutate(
      { plan, interval: "month" },
      {
        onError: (error) =>
          notify.error({ title: error instanceof ApiError ? error.message : String(error) }),
      },
    );
  }

  async function addOn() {
    const kind = step.kind === "buy_bundle" ? "bundle" : "agent";
    const key = String(kind === "bundle" ? detail.bundle : detail.agent);
    const ok = await confirm({
      title: fill(w.buyTitle, { name: kind === "bundle" ? bundleName : agentName(key) }),
      description: fill(w.buyBody, { price: money(detail.monthly_price) }),
      confirmLabel: w.confirm,
    });
    if (!ok) return;
    buy.mutate(
      { kind, key, intention_id: intentionId ?? null },
      {
        onError: (error) =>
          notify.error({ title: error instanceof ApiError ? error.message : String(error) }),
      },
    );
  }

  const link = (href: string) => (
    <Link href={href} className={buttonVariants({ variant: "outline", size: "sm" })}>
      {w.go}
      <ArrowRight className="rtl:-scale-x-100 size-3.5" aria-hidden="true" />
    </Link>
  );
  let action: React.ReactNode = null;
  if (step.kind === "connect_source") action = link(routes.sources());
  else if (step.kind === "configure_model") action = link(routes.settings());
  else if (step.kind === "enable") action = link(`${routes.capabilities()}?view=configuration`);
  else if (step.kind === "contact_sales") action = link(routes.billing());
  else if (step.kind === "change_plan" && pays)
    action = (
      <Button
        type="button"
        size="sm"
        disabled={checkout.isPending}
        onClick={() => void changePlan()}
        data-testid="feasibility-change-plan"
      >
        {fill(w.steps.change_plan, { plan: planName, price: money(detail.monthly_price) })}
      </Button>
    );
  else if ((step.kind === "buy_add_on" || step.kind === "buy_bundle") && pays)
    action = (
      <Button
        type="button"
        size="sm"
        disabled={buy.isPending}
        onClick={() => void addOn()}
        data-testid="feasibility-buy"
      >
        {said}
      </Button>
    );
  const paid = step.kind === "change_plan" || step.kind === "buy_add_on" || step.kind === "buy_bundle";
  return (
    <li
      className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-shell-line px-3 py-2 text-[0.8125rem] text-brand-navy"
      data-testid="feasibility-step"
      data-kind={step.kind}
    >
      <span className="min-w-0 flex-1">{said}</span>
      {action ?? (paid ? <span className="text-xs text-shell-muted">{t.intentions.feasibility.steps.ask_admin}</span> : null)}
    </li>
  );
}

/** What it takes to carry an intention through here, once read (LEKA-439). */
export function FeasibilityCard({ intentionId }: { intentionId: string }) {
  const found = useIntentionFeasibility(intentionId);
  return found.data ? <FeasibilityPanel feasibility={found.data} intentionId={intentionId} /> : null;
}
