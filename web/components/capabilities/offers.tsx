"use client";

import { ArrowRight, BadgeCheck, Check, Clock, Lock, Package, Plus, ShoppingCart } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { cn } from "cn";

import { Card } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { MarketTile, marketOf } from "@/components/capabilities/market-mark";
import { useConfirm } from "@/components/interactions/confirm";
import { usePermissions } from "@/components/shell/shell-provider";
import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { agentTitle } from "@/lib/agent-title";
import { ApiError } from "@/lib/api";
import { euros, type AddOns, type AgentOffer, type BundleOffer } from "@/lib/billing";
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

/**
 * Where an agent stands for this workspace (LEKA-467), the server's word —
 * one of five, said in words, never a mark alone:
 *
 *     included     its plan includes it — or LEKA granted every agent
 *     owned        bought: an option active
 *     option       on sale, not bought: a paid monthly option
 *     upgrade      its plan runs no agent: a higher plan first
 *     unavailable  not on sale: nothing to buy
 */
export type AgentState = "included" | "owned" | "option" | "upgrade" | "unavailable";

export function agentStateOf(offers: AddOns | undefined, key: string): AgentState | null {
  if (!offers) return null;
  const offer = offers.agents.find((a) => a.key === key);
  if (!offer || offer.why === "not_for_sale") return "unavailable";
  if (offer.included || offers.every) return "included";
  if (offer.why === "plan_required") return "upgrade";
  if (offer.owned) return "owned";
  return "option";
}

const STATE_TONES: Record<AgentState, "success" | "violet" | "warning" | "neutral"> = {
  included: "success",
  owned: "success",
  option: "violet",
  upgrade: "warning",
  unavailable: "neutral",
};

/** An agent's state, in words: what the line says before any action. */
export function AgentStateSaid({ agentKey }: { agentKey: string }) {
  const t = useDictionary();
  const w = t.catalogue.offers;
  const offers = useAddOns();
  const state = agentStateOf(offers.data, agentKey);
  if (!state) return null;
  return (
    <Pill tone={STATE_TONES[state]} data-testid="agent-state" data-state={state}>
      {state === "included" && offers.data?.every && !offers.data.agents.find((a) => a.key === agentKey)?.included
        ? w.states.granted
        : w.states[state]}
    </Pill>
  );
}

/** An agent's price excluding VAT and the action its state allows
 * (LEKA-467): « Acheter », « Gérer », « Voir les formules » — included or
 * unavailable, none. Its price only when it is sold. */
export function AgentOfferAction({ agentKey }: { agentKey: string }) {
  const t = useDictionary();
  const w = t.catalogue.offers;
  const { format } = useLocale();
  const offers = useAddOns();
  const buy = useBuy();
  const may = useMayBuy();
  const offer = offers.data?.agents.find((a) => a.key === agentKey);
  const state = agentStateOf(offers.data, agentKey);
  if (!offers.data || !state) return null;
  return (
    <span
      className="flex shrink-0 flex-col items-end gap-1"
      data-testid="agent-price"
      data-owned={offer?.owned ?? false}
      data-state={state}
    >
      {offer && state !== "unavailable" ? (
        <span className="text-[0.8125rem] font-semibold whitespace-nowrap tabular-nums text-brand-navy">
          {euros(offer.monthly_price, format)}
          <span className="text-[0.6875rem] font-normal text-shell-muted"> {w.monthHt}</span>
        </span>
      ) : null}
      {offer ? (
        <span className="text-[0.6875rem] text-shell-muted" data-testid="agent-tier">
          {(w.tiers as Record<string, string>)[offer.tier] ?? offer.tier}
        </span>
      ) : null}
      {state === "option" && offer ? (
        may ? (
          <Button
            type="button"
            size="xs"
            disabled={buy.isPending}
            aria-label={fill(w.buyNamed, { name: agentTitle(t, offer.key, offer.title) })}
            onClick={() => buy.mutate({ kind: "agent", key: offer.key }, { onError: (error) => bought(t, error) })}
            data-testid="agent-buy"
          >
            <Plus className="size-3" aria-hidden="true" />
            {w.buy}
          </Button>
        ) : (
          <span className="text-xs text-shell-muted" title={w.askAdmin}>
            {w.askAdminShort}
          </span>
        )
      ) : state === "owned" ? (
        <Link
          href={routes.billing()}
          className="text-xs font-medium text-shell-nav-active hover:underline"
          data-testid="agent-manage"
        >
          {w.manage}
        </Link>
      ) : state === "upgrade" ? (
        <Link
          href={routes.billingPlans()}
          className="text-xs font-medium whitespace-nowrap text-shell-nav-active hover:underline"
          data-testid="agent-upgrade"
        >
          {fill(w.fromPlan, { plan: planName(offers.data.minimum_plan) })}
        </Link>
      ) : null}
    </span>
  );
}

/** What a card of the home does, by the agent's state (LEKA-497): « Ouvrir
 * l'agent » where it is the workspace's, « Acheter l'agent » — its price and
 * what happens said, confirmed, then Stripe's page — where it is an option
 * this person may buy, « Voir les options » where a plan above is needed;
 * nothing where it is not sold. The agent is granted once Stripe says paid. */
export function AgentCardAction({ agentKey }: { agentKey: string }) {
  const t = useDictionary();
  const w = t.catalogue.offers;
  const { format } = useLocale();
  const confirm = useConfirm();
  const offers = useAddOns();
  const buy = useBuy();
  const may = useMayBuy();
  const offer = offers.data?.agents.find((a) => a.key === agentKey);
  const state = agentStateOf(offers.data, agentKey);
  if (!offer || !state || state === "unavailable") return null;
  const link = "relative z-10 text-xs font-medium text-shell-nav-active hover:underline";
  if (state === "included" || state === "owned") {
    return (
      <Link href={routes.capability(offer.key)} className={link} data-testid="agent-open">
        {w.open}
      </Link>
    );
  }
  if (state === "upgrade") {
    return (
      <Link href={routes.billingPlans()} className={link} data-testid="agent-upgrade">
        {w.seeOptions}
      </Link>
    );
  }
  if (!may) {
    return (
      <span className="text-xs text-shell-muted" title={w.askAdmin}>
        {w.askAdminShort}
      </span>
    );
  }
  return (
    <Button
      type="button"
      size="xs"
      className="relative z-10"
      disabled={buy.isPending}
      aria-label={fill(w.buyNamed, { name: agentTitle(t, offer.key, offer.title) })}
      data-testid="agent-buy"
      onClick={async () => {
        const ok = await confirm({
          title: fill(w.buyTitle, { name: agentTitle(t, offer.key, offer.title) }),
          description: fill(w.buyBody, { price: euros(offer.monthly_price, format) }),
          confirmLabel: w.buyConfirm,
        });
        if (ok) buy.mutate({ kind: "agent", key: offer.key }, { onError: (error) => bought(t, error) });
      }}
    >
      <ShoppingCart className="size-3" aria-hidden="true" />
      {w.buyAgent}
    </Button>
  );
}

/** Buying an agent from anywhere (LEKA-471): whether this person may, and
 * the purchase — Stripe's page, the agent granted once Stripe says paid. */
export function useAgentPurchase() {
  const t = useDictionary();
  const buy = useBuy();
  const may = useMayBuy();
  return {
    may,
    pending: buy.isPending,
    buy: (key: string) => buy.mutate({ kind: "agent", key }, { onError: (error) => bought(t, error) }),
  };
}

/** The home's « + » on an agent (LEKA-470, its mockup): bought from there,
 * where it is an option this person may buy — anywhere else, nothing. */
export function AgentAdd({ agentKey }: { agentKey: string }) {
  const t = useDictionary();
  const w = t.catalogue.offers;
  const offers = useAddOns();
  const buy = useBuy();
  const may = useMayBuy();
  const offer = offers.data?.agents.find((a) => a.key === agentKey);
  if (!offer || !may || agentStateOf(offers.data, agentKey) !== "option") return null;
  const named = fill(w.buyNamed, { name: agentTitle(t, offer.key, offer.title) });
  return (
    <button
      type="button"
      className="flex size-8 shrink-0 items-center justify-center rounded-full border border-shell-line text-shell-nav-active outline-none hover:bg-brand-violet-soft focus-visible:ring-3 focus-visible:ring-brand-violet/40 disabled:opacity-50"
      disabled={buy.isPending}
      aria-label={named}
      title={named}
      onClick={() => buy.mutate({ kind: "agent", key: offer.key }, { onError: (error) => bought(t, error) })}
      data-testid="agent-buy"
    >
      <Plus className="size-4" aria-hidden="true" />
    </button>
  );
}

/** An agent's price and standing, on its line of the catalogue — `compact`:
 * the price, then one round mark, as the catalogue's mockup (LEKA-460). */
export function AgentPrice({ agentKey, compact = false }: { agentKey: string; compact?: boolean }) {
  const t = useDictionary();
  const w = t.catalogue.offers;
  const { format } = useLocale();
  const offers = useAddOns();
  const buy = useBuy();
  const may = useMayBuy();
  const offer = offers.data?.agents.find((a) => a.key === agentKey);
  if (!offer || !offers.data) return null;
  const tiers = w.tiers as Record<string, string>;
  if (compact) {
    const round = "flex size-7 shrink-0 items-center justify-center rounded-full border";
    const said = (text: string) => <span className="sr-only">{text}</span>;
    return (
      <span className="flex shrink-0 items-center gap-2" data-testid="agent-price" data-owned={offer.owned}>
        <span className="text-[0.8125rem] font-semibold tabular-nums text-brand-navy">
          {euros(offer.monthly_price, format)}
          {said(` ${w.month}`)}
        </span>
        {offer.included ? (
          <span className={cn(round, "border-state-success/30 bg-state-success/10 text-state-success")} title={w.includedInPlan}>
            <Check className="size-3.5" aria-hidden="true" />
            {said(w.includedInPlan)}
          </span>
        ) : offer.owned ? (
          <span className={cn(round, "border-state-success/30 bg-state-success/10 text-state-success")} title={w.active}>
            <Check className="size-3.5" aria-hidden="true" />
            {said(w.active)}
          </span>
        ) : offer.why === "plan_required" ? (
          <Link
            href={routes.billingPlans()}
            className={cn(round, "border-shell-line text-shell-muted hover:bg-shell-canvas")}
            title={fill(w.fromPlan, { plan: planName(offers.data.minimum_plan) })}
          >
            <Lock className="size-3.5" aria-hidden="true" />
            {said(fill(w.fromPlan, { plan: planName(offers.data.minimum_plan) }))}
          </Link>
        ) : may ? (
          <button
            type="button"
            className={cn(round, "border-shell-line text-shell-nav-active hover:bg-brand-violet-soft disabled:opacity-50")}
            disabled={buy.isPending}
            title={`${w.buy} — ${agentTitle(t, offer.key, offer.title)}`}
            aria-label={`${w.buy} — ${agentTitle(t, offer.key, offer.title)}`}
            onClick={() =>
              buy.mutate({ kind: "agent", key: offer.key }, { onError: (error) => bought(t, error) })
            }
            data-testid="agent-buy"
          >
            <Plus className="size-3.5" aria-hidden="true" />
          </button>
        ) : (
          <span className={cn(round, "border-shell-line text-shell-muted")} title={w.locked}>
            <Lock className="size-3.5" aria-hidden="true" />
            {said(w.locked)}
          </span>
        )}
      </span>
    );
  }
  return (
    <span className="flex flex-wrap items-center gap-2" data-testid="agent-price" data-owned={offer.owned}>
      <span className="text-xs font-semibold text-brand-navy">
        {fill(w.perMonth, { price: euros(offer.monthly_price, format) })}
      </span>
      <Pill tone="neutral">{tiers[offer.tier] ?? offer.tier}</Pill>
      {offer.included ? (
        <Pill tone="success" dot>
          {w.includedInPlan}
        </Pill>
      ) : offer.owned ? (
        <Pill tone="success" dot>
          {w.active}
        </Pill>
      ) : offer.why === "plan_required" ? (
        <Link href={routes.billingPlans()} className="text-xs font-medium text-brand-violet hover:underline">
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
  markets,
  minimum,
  runsAgents,
  picked,
  onPick,
}: {
  bundle: BundleOffer;
  titles: Map<string, string>;
  /** In the marketplace: picked to buy with others, in one order (LEKA-500). */
  picked?: boolean;
  onPick?: () => void;
  /** Each agent's domain, to draw it as on its own card (LEKA-493). */
  markets: Map<string, string>;
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
  const tone = BUNDLE_TONES[bundle.key] ?? BUNDLE_TONES.default;
  const members = bundle.members ?? [];
  // A saving only where it can be shown (Karim, 2026-10-15): computed from
  // every member's price, and the bundle on sale.
  const saving = bundle.sellable && bundle.alone_price !== null && bundle.discount_percent !== null;
  return (
    <li
      className="flex flex-col overflow-hidden rounded-xl border border-shell-line bg-white"
      data-testid="bundle"
      data-key={bundle.key}
    >
      <div className={cn("flex items-center gap-2 bg-linear-to-r px-4 py-2.5 text-white", tone.band)}>
        <Package className="size-4.5" aria-hidden="true" />
        <h3 className="text-[0.9375rem] font-semibold">{name}</h3>
      </div>
      <div className="flex flex-1 flex-col gap-3 p-4">
        {value ? <p className="text-[0.8125rem] text-shell-muted">{value}</p> : null}
        <p className="flex flex-wrap items-baseline gap-2">
          <span className="text-[1.5rem] font-bold text-brand-navy">{euros(bundle.monthly_price, format)}</span>
          <span className="text-xs text-shell-muted">{w.month}</span>
          {saving ? (
            <>
              <span className="text-xs text-shell-muted line-through">{euros(bundle.alone_price as number, format)}</span>
              <Pill tone="success">{fill(w.save, { percent: bundle.discount_percent as number })}</Pill>
            </>
          ) : null}
        </p>
        <ul className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-brand-navy" data-testid="bundle-members">
          {members.map((member) => (
            <li
              key={member.key}
              className={cn("flex min-w-0 items-center gap-1.5", !member.agent && "text-shell-muted")}
              data-built={member.agent ? "true" : "false"}
              title={member.agent ? undefined : w.notBuilt}
            >
              {member.agent && markets.get(member.agent) ? (
                // Its domain's mark, as on its own card (LEKA-493).
                <MarketTile
                  market={markets.get(member.agent) as string}
                  label={(t.catalogue.markets as Record<string, string>)[markets.get(member.agent) as string] ?? ""}
                  className="size-5 rounded [&_svg]:size-3"
                />
              ) : member.agent ? (
                <BadgeCheck className="size-3.5 shrink-0 text-state-success" aria-hidden="true" />
              ) : (
                <Clock className="size-3.5 shrink-0" aria-hidden="true" />
              )}
              <span className="truncate">
                {member.agent ? (titles.get(member.agent) ?? member.name) : member.name}
              </span>
              {member.agent ? null : <span className="sr-only">· {w.notBuilt}</span>}
            </li>
          ))}
        </ul>
        <p className="mt-auto text-center text-xs font-medium text-brand-navy">
          {fill(w.agentsIn, { count: members.length })}
        </p>
        {!bundle.sellable ? (
          // Some of its agents are not built: not sold (LEKA-454).
          <p
            className="flex h-9 items-center justify-center rounded-lg bg-shell-canvas text-[0.8125rem] font-medium text-shell-muted"
            title={w.bundleSoon}
            data-testid="bundle-soon"
          >
            {w.soon}
          </p>
        ) : bundle.owned ? (
          <Pill tone="success" dot>
            {w.active}
          </Pill>
        ) : !runsAgents ? (
          <Link href={routes.billingPlans()} className={buttonVariants({ variant: "outline", className: "w-full" })}>
            {fill(w.fromPlan, { plan: planName(minimum) })}
          </Link>
        ) : may ? (
          <Button
            type="button"
            className={cn("w-full text-white", tone.button)}
            disabled={buy.isPending}
            onClick={() =>
              buy.mutate({ kind: "bundle", key: bundle.key }, { onError: (error) => bought(t, error) })
            }
            data-testid="bundle-buy"
          >
            {w.choose}
            <ArrowRight className="size-4 rtl:-scale-x-100" aria-hidden="true" />
          </Button>
        ) : (
          <p className="text-xs text-shell-muted">{w.askAdmin}</p>
        )}
        {onPick && bundle.sellable && !bundle.owned && runsAgents && may ? (
          <label className="flex cursor-pointer items-center justify-center gap-2 text-xs text-brand-navy" data-testid="bundle-pick">
            <input
              type="checkbox"
              checked={Boolean(picked)}
              onChange={onPick}
              className="size-4 accent-brand-violet"
            />
            {w.pick}
          </label>
        ) : null}
      </div>
    </li>
  );
}

/** Each bundle's colour, as the mockup gives it (LEKA-460). */
const BUNDLE_TONES: Record<string, { band: string; button: string }> = {
  engineering: { band: "from-blue-600 to-blue-500", button: "bg-blue-600 hover:bg-blue-700" },
  "ship-safe": { band: "from-violet-600 to-violet-500", button: "bg-violet-600 hover:bg-violet-700" },
  "incident-response": { band: "from-rose-600 to-rose-500", button: "bg-rose-600 hover:bg-rose-700" },
  "security-reliability": {
    band: "from-emerald-600 to-emerald-500",
    button: "bg-emerald-600 hover:bg-emerald-700",
  },
  "frontend-craft": { band: "from-orange-500 to-amber-500", button: "bg-orange-500 hover:bg-orange-600" },
  default: { band: "from-brand-violet to-brand-violet", button: "bg-brand-violet" },
};

/** The bundles, as the reference composes them: sold once every agent they
 * name is built, their saving computed (LEKA-454). */
export function Bundles({ selectable = false }: { selectable?: boolean }) {
  const t = useDictionary();
  const w = t.catalogue.offers;
  const offers = useAddOns();
  const [picked, setPicked] = useState<string[]>([]);
  const data = offers.data;
  if (!data?.available || !data.bundles.length) return null;
  const titles = new Map(data.agents.map((a: AgentOffer) => [a.key, agentTitle(t, a.key, a.title)]));
  const markets = new Map(data.agents.map((a: AgentOffer) => [a.key, marketOf(a)]));
  const savings = data.bundles
    .filter((b) => b.sellable && b.discount_percent !== null)
    .map((b) => b.discount_percent as number);
  const best = savings.length ? Math.max(...savings) : null;
  return (
    // id: the header's « Bundles » opens the catalogue here (LEKA-494).
    <section id="bundles" className="scroll-mt-4 space-y-3" aria-labelledby="bundles-title" data-testid="bundles">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 id="bundles-title" className="text-[1.25rem] font-bold text-brand-navy">
            {w.bundlesTitle}
          </h2>
          <p className="text-[0.8125rem] text-shell-muted">{w.bundlesLead}</p>
        </div>
        {best !== null ? (
          <p className="rounded-lg border border-shell-line bg-brand-violet-soft px-3 py-1.5 text-xs" data-testid="bundles-saving">
            <span className="font-semibold text-shell-nav-active">{fill(w.upTo, { percent: best })}</span>{" "}
            <span className="text-shell-muted">{w.upToLead}</span>
          </p>
        ) : null}
      </div>
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
        {data.bundles.map((bundle) => (
          <BundleCard
            key={bundle.key}
            bundle={bundle}
            titles={titles}
            markets={markets}
            picked={picked.includes(bundle.key)}
            onPick={
              selectable
                ? () =>
                    setPicked((now) =>
                      now.includes(bundle.key) ? now.filter((k) => k !== bundle.key) : [...now, bundle.key],
                    )
                : undefined
            }
            minimum={data.minimum_plan}
            runsAgents={data.runs_agents}
          />
        ))}
      </ul>
      {selectable && picked.length ? (
        <BundleSelection
          picked={data.bundles.filter((b) => picked.includes(b.key))}
          onClear={() => setPicked([])}
        />
      ) : null}
    </section>
  );
}

/** « Acheter la sélection » (LEKA-500): the bundles picked, each its price,
 * their total, said and confirmed — then one Stripe Checkout, one
 * subscription, each bundle its own right once Stripe says paid. */
function BundleSelection({ picked, onClear }: { picked: BundleOffer[]; onClear: () => void }) {
  const t = useDictionary();
  const w = t.catalogue.offers;
  const { format, locale } = useLocale();
  const confirm = useConfirm();
  const buy = useBuy();
  const name = (b: BundleOffer) => (locale.startsWith("en") ? b.name.en : b.name.fr);
  const total = picked.reduce((sum, b) => sum + b.monthly_price, 0);
  return (
    <div
      className="sticky bottom-3 z-20 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-brand-violet/30 bg-white px-4 py-3 shadow-md"
      data-testid="bundle-selection"
    >
      <p className="text-[0.875rem] text-brand-navy">
        <span className="font-semibold">{fill(w.picked, { count: picked.length })}</span>
        {" · "}
        <span className="tabular-nums" data-testid="bundle-selection-total">
          {euros(total, format)} {w.monthHt}
        </span>
      </p>
      <div className="flex items-center gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onClear}>
          {w.clear}
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={buy.isPending}
          data-testid="bundle-selection-buy"
          onClick={async () => {
            const lines = picked.map((b) => `${name(b)} : ${euros(b.monthly_price, format)} ${w.monthHt}`);
            const ok = await confirm({
              title: fill(w.buySelectionTitle, { count: picked.length }),
              description: `${lines.join(" · ")}. ${fill(w.buySelectionBody, {
                total: `${euros(total, format)} ${w.monthHt}`,
              })}`,
              confirmLabel: w.buyConfirm,
            });
            if (!ok) return;
            const keys = picked.map((b) => b.key).join(",");
            buy.mutate(
              picked.length === 1 ? { kind: "bundle", key: keys } : { kind: "bundles", key: keys },
              { onError: (error) => bought(t, error) },
            );
          }}
        >
          {w.buySelection}
        </Button>
      </div>
    </div>
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
  const titles = new Map(data.agents.map((a) => [a.key, agentTitle(t, a.key, a.title)]));
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
