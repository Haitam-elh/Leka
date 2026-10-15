"use client";

import { BadgeCheck, Lock, Package, ShoppingCart } from "lucide-react";
import Link from "next/link";

import { Card, IconTile } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { usePermissions } from "@/components/shell/shell-provider";
import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { euros, type AgentOffer, type BundleOffer } from "@/lib/billing";
import { useAddOns, useBuy, useEntitlements } from "@/lib/billing-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

/**
 * What is sold besides a plan (2026-10-14, the product call: « aucun prix
 * n'est affiché sur les agents ni sur les bundles »): each agent's price and
 * whether this workspace owns it, the bundles — cheaper than their agents
 * one by one — and what it owns. Bought on Stripe's page; owned once Stripe
 * says it is paid, never on the way back.
 *
 * Who may buy is who may change the workspace (workspace:update); anyone
 * else is told to ask.
 */

function useMayBuy(): boolean {
  return usePermissions()?.includes("workspace:update") ?? false;
}

function planName(plan: string): string {
  return plan.charAt(0).toUpperCase() + plan.slice(1);
}

function bought(t: ReturnType<typeof useDictionary>, error: unknown) {
  const said = t.catalogue.offers as unknown as Record<string, string>;
  notify.error({
    title: error instanceof ApiError ? (said[error.code ?? ""] ?? error.message) : said.failed,
  });
}

/** An agent's price and standing, on its line of the catalogue. */
export function AgentPrice({ agentKey }: { agentKey: string }) {
  const t = useDictionary();
  const w = t.catalogue.offers;
  const { format } = useLocale();
  const offers = useAddOns();
  const buy = useBuy();
  const may = useMayBuy();
  const offer = offers.data?.agents.find((a) => a.key === agentKey);
  if (!offer || !offers.data) return null;
  const tiers = w.tiers as Record<string, string>;
  return (
    <span className="flex flex-wrap items-center gap-2" data-testid="agent-price" data-owned={offer.owned}>
      <span className="text-xs font-semibold text-brand-navy">
        {fill(w.perMonth, { price: euros(offer.monthly_price, format) })}
      </span>
      <Pill tone="neutral">{tiers[offer.tier] ?? offer.tier}</Pill>
      {offer.owned ? (
        <Pill tone="success" dot>
          {w.active}
        </Pill>
      ) : offer.why === "plan_required" ? (
        <Link href={routes.billing()} className="text-xs font-medium text-brand-violet hover:underline">
          {fill(w.fromPlan, { plan: planName(offers.data.minimum_plan) })}
        </Link>
      ) : may ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={buy.isPending}
          onClick={() =>
            buy.mutate({ kind: "agent", key: offer.key }, { onError: (error) => bought(t, error) })
          }
          data-testid="agent-buy"
        >
          <ShoppingCart className="size-3.5" aria-hidden="true" />
          {w.buy}
        </Button>
      ) : (
        <Pill tone="warning">
          <Lock className="size-3" aria-hidden="true" />
          {w.locked}
        </Pill>
      )}
    </span>
  );
}

function BundleCard({
  bundle,
  titles,
  minimum,
  runsAgents,
}: {
  bundle: BundleOffer;
  titles: Map<string, string>;
  minimum: string;
  runsAgents: boolean;
}) {
  const t = useDictionary();
  const w = t.catalogue.offers;
  const { format, locale } = useLocale();
  const buy = useBuy();
  const may = useMayBuy();
  const name = locale.startsWith("en") ? bundle.name.en : bundle.name.fr;
  const value = bundle.value ? (locale.startsWith("en") ? bundle.value.en : bundle.value.fr) : null;
  return (
    <li
      className="flex flex-col gap-3 rounded-xl border border-shell-line bg-white p-4"
      data-testid="bundle"
      data-key={bundle.key}
    >
      <div className="flex items-center gap-2.5">
        <IconTile icon={Package} tone="violet" className="size-9" />
        <div className="min-w-0">
          <h3 className="text-[1rem] font-semibold text-brand-navy">{name}</h3>
          {value ? <p className="text-[0.8125rem] text-shell-muted">{value}</p> : null}
        </div>
      </div>
      <p className="flex flex-wrap items-baseline gap-2">
        <span className="text-[1.5rem] font-semibold text-brand-navy">
          {euros(bundle.monthly_price, format)}
        </span>
        <span className="text-xs text-shell-muted">{w.month}</span>
        <span className="text-xs text-shell-muted line-through">{euros(bundle.alone_price, format)}</span>
        <Pill tone="success">{fill(w.save, { percent: bundle.discount_percent })}</Pill>
      </p>
      <ul className="space-y-1 text-[0.8125rem] text-brand-navy">
        {bundle.agents.map((key) => (
          <li key={key} className="flex items-center gap-1.5">
            <BadgeCheck className="size-3.5 text-state-success" aria-hidden="true" />
            {titles.get(key) ?? key}
          </li>
        ))}
      </ul>
      <div className="mt-auto">
        {bundle.owned ? (
          <Pill tone="success" dot>
            {w.active}
          </Pill>
        ) : !runsAgents ? (
          <Link href={routes.billing()} className={buttonVariants({ variant: "outline", className: "w-full" })}>
            {fill(w.fromPlan, { plan: planName(minimum) })}
          </Link>
        ) : may ? (
          <Button
            type="button"
            className="w-full"
            disabled={buy.isPending}
            onClick={() =>
              buy.mutate({ kind: "bundle", key: bundle.key }, { onError: (error) => bought(t, error) })
            }
            data-testid="bundle-buy"
          >
            {w.choose}
          </Button>
        ) : (
          <p className="text-xs text-shell-muted">{w.askAdmin}</p>
        )}
      </div>
    </li>
  );
}

/** The bundles: agents together, cheaper than one by one. */
export function Bundles() {
  const t = useDictionary();
  const w = t.catalogue.offers;
  const offers = useAddOns();
  const data = offers.data;
  if (!data?.available || !data.bundles.length) return null;
  const titles = new Map(data.agents.map((a: AgentOffer) => [a.key, a.title]));
  return (
    <section className="space-y-3" aria-labelledby="bundles-title" data-testid="bundles">
      <div>
        <h2 id="bundles-title" className="text-[1.0625rem] font-semibold text-brand-navy">
          {w.bundlesTitle}
        </h2>
        <p className="text-[0.8125rem] text-shell-muted">{w.bundlesLead}</p>
      </div>
      <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {data.bundles.map((bundle) => (
          <BundleCard
            key={bundle.key}
            bundle={bundle}
            titles={titles}
            minimum={data.minimum_plan}
            runsAgents={data.runs_agents}
          />
        ))}
      </ul>
    </section>
  );
}

/** « Mes capacités »: what this workspace owns — its plan's own, the agents
 * and bundles bought, or every agent LEKA granted it. */
export function Owned() {
  const t = useDictionary();
  const w = t.catalogue.offers;
  const offers = useAddOns();
  const owned = useEntitlements();
  const data = offers.data;
  if (!data || !owned.data) return null;
  const titles = new Map(data.agents.map((a) => [a.key, a.title]));
  const bundles = new Map(data.bundles.map((b) => [b.key, b]));
  return (
    <Card title={w.ownedTitle} icon={<BadgeCheck className="size-4 text-shell-muted" aria-hidden="true" />}>
      <p className="mb-2 text-[0.8125rem] text-brand-navy">
        {fill(w.plan, { plan: planName(data.plan) })} · {w.included}
      </p>
      {owned.data.length ? (
        <ul className="space-y-1.5" data-testid="owned">
          {owned.data.map((row) => (
            <li key={`${row.kind}:${row.key}`} className="text-[0.875rem] text-brand-navy" data-testid="owned-item">
              {row.kind === "all"
                ? w.ownedEvery
                : row.kind === "bundle"
                  ? fill(w.ownedBundle, { name: bundles.get(row.key)?.name.fr ?? row.key })
                  : fill(w.ownedAgent, { name: titles.get(row.key) ?? row.key })}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[0.8125rem] text-shell-muted">{w.ownedNone}</p>
      )}
    </Card>
  );
}
