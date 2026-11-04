"use client";

import { ArrowLeft, CircleCheck, Lightbulb, Package, Receipt, SearchX, Target, Users } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";

import { cn } from "cn";

import { ProductSection, ProductTile, useSay } from "@/components/capabilities/agent-product";
import { MarketTile, marketOf } from "@/components/capabilities/market-mark";
import {
  AgentStateSaid,
  bundleName,
  bundleSaving,
  type BundleState,
  BundleStateSaid,
  bundleStateOf,
  bundleTone,
  bundleValue,
  useBundlePurchase,
} from "@/components/capabilities/offers";
import { Pill } from "@/components/intelligence/pill";
import { PageContainer } from "@/components/shell/page-container";
import { ErrorState } from "@/components/states/error-state";
import { StatePanel } from "@/components/states/state-panel";
import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { productOf } from "@/lib/agent-products";
import { agentTitle } from "@/lib/agent-title";
import { type AddOns, type BundleOffer, euros } from "@/lib/billing";
import { useAddOns } from "@/lib/billing-queries";
import { bundleProductOf, type BundleProduct } from "@/lib/bundle-products";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { useNamePage } from "@/lib/navigation/page-name";

/**
 * A bundle's page (LEKA-531), one template for every bundle: what it brings
 * and for whom, the problem it solves, three reasons, when it helps; every
 * agent it includes, each with its role and its own page; its price and
 * cadence, and — only where it is computed from every agent's price today —
 * what it saves against its agents bought one by one; where it stands for
 * this workspace, and the way to choose it.
 *
 * Its words are lib/bundle-products.ts; everything that changes is the
 * API's (GET /billing/add-ons, the catalogue): price, cadence, agents,
 * their prices, the saving, whether it is owned. Its state is the card's
 * (offers.tsx, bundleStateOf): the same word on both. Chosen, it takes the
 * flow every purchase takes — said, confirmed, Stripe's Checkout.
 */

export function BundleScreen() {
  const t = useDictionary();
  const w = t.catalogue.bundle;
  const { locale } = useLocale();
  const params = useParams<{ bundleKey: string }>();
  const pathname = usePathname() ?? "/";
  const key = decodeURIComponent(params.bundleKey ?? "");
  const offers = useAddOns();
  const bundle = offers.data?.bundles.find((b) => b.key === key);
  useNamePage(pathname, bundle ? bundleName(bundle, locale) : undefined);

  let body: React.ReactNode;
  if (offers.isError) {
    body = <ErrorState error={offers.error} onRetry={() => void offers.refetch()} />;
  } else if (!offers.data) {
    body = <div className="mt-5 h-96 animate-pulse rounded-2xl bg-shell-canvas" aria-hidden="true" data-testid="bundle-loading" />;
  } else if (!bundle) {
    body = (
      <StatePanel
        icon={SearchX}
        title={w.notFound}
        actions={
          <Link href={`${routes.capabilities()}#bundles`} className={buttonVariants({ variant: "outline" })}>
            {w.back}
          </Link>
        }
      />
    );
  } else {
    body = <BundlePage bundle={bundle} offers={offers.data} />;
  }
  return (
    <PageContainer>
      <Link
        href={`${routes.capabilities()}#bundles`}
        className="inline-flex items-center gap-2 rounded-lg border border-shell-line bg-white px-3 py-1.5 text-[0.8125rem] font-medium text-brand-navy outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        data-testid="bundle-back"
      >
        <ArrowLeft className="size-4 rtl:-scale-x-100" aria-hidden="true" />
        {w.back}
      </Link>
      {body}
    </PageContainer>
  );
}

export function BundlePage({ bundle, offers }: { bundle: BundleOffer; offers: AddOns }) {
  const t = useDictionary();
  const state = bundleStateOf(offers, bundle);
  const product = bundleProductOf(bundle.key);
  return (
    <div
      className="mt-5 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_18rem] xl:grid-cols-[minmax(0,1fr)_20rem]"
      data-testid="bundle-page"
      data-key={bundle.key}
      data-state={state ?? undefined}
    >
      <div className="@container min-w-0 space-y-5">
        <Hero bundle={bundle} offers={offers} product={product} state={state} />
        <div className="lg:hidden">
          <ChooseCard bundle={bundle} offers={offers} state={state} where="top" />
        </div>
        {product ? <WhySection product={product} /> : null}
        {product ? <UseCasesSection product={product} /> : null}
        <AgentsSection bundle={bundle} offers={offers} />
        {state === "contract" ? null : <PricingSection bundle={bundle} offers={offers} />}
      </div>
      <aside className="hidden lg:block" aria-label={t.catalogue.bundle.choose}>
        <ChooseCard bundle={bundle} offers={offers} state={state} where="side" />
      </aside>
    </div>
  );
}

function Hero({
  bundle,
  offers,
  product,
  state,
}: {
  bundle: BundleOffer;
  offers: AddOns;
  product: BundleProduct | null;
  state: BundleState | null;
}) {
  const t = useDictionary();
  const w = t.catalogue.bundle;
  const say = useSay();
  const { format, locale } = useLocale();
  const tone = bundleTone(bundle.key);
  const members = bundle.members ?? [];
  return (
    <section
      aria-labelledby="bundle-title"
      className="overflow-hidden rounded-2xl border border-shell-line bg-white"
      data-testid="bundle-hero"
    >
      <div className={cn("h-2 bg-linear-to-r", tone.band)} aria-hidden="true" />
      <div className="flex flex-col gap-5 p-5 md:flex-row md:items-start md:p-6">
        <span className={cn("flex size-16 shrink-0 items-center justify-center rounded-2xl md:size-20", tone.soft)}>
          <Package className="size-8 md:size-10" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <Pill tone="violet">{w.badge}</Pill>
          <h1
            id="bundle-title"
            className="mt-2 text-[1.75rem] leading-tight font-bold tracking-[-0.02em] text-balance text-brand-navy md:text-[2.25rem]"
          >
            {bundleName(bundle, locale)}
          </h1>
          <p className="mt-2 max-w-2xl text-[0.9375rem] text-shell-muted md:text-base" data-testid="bundle-promise">
            {product ? say(product.promise) : bundleValue(bundle, locale)}
          </p>
          {product ? (
            <p className="mt-3 max-w-2xl text-[0.875rem] text-brand-navy" data-testid="bundle-audience">
              <span className="font-semibold">
                {w.forWhom}
                {t.shell.colon}
              </span>
              {say(product.audience)}
            </p>
          ) : null}
          <div className="mt-4 flex flex-wrap items-center gap-2.5">
            <Pill tone="neutral">{fill(w.agents, { count: members.length })}</Pill>
            {state !== "contract" ? (
              <span className="text-[0.9375rem] font-semibold tabular-nums text-brand-navy" data-testid="bundle-hero-price">
                {euros(bundle.monthly_price, format)}{" "}
                <span className="text-[0.8125rem] font-normal text-shell-muted">{w.perMonth}</span>
              </span>
            ) : null}
            <BundleStateSaid state={state} minimum={offers.minimum_plan} />
          </div>
        </div>
      </div>
    </section>
  );
}

function WhySection({ product }: { product: BundleProduct }) {
  const t = useDictionary();
  const say = useSay();
  return (
    <ProductSection id="overview" icon={Target} title={t.catalogue.bundle.why}>
      <p className="max-w-3xl text-[0.9375rem] text-shell-muted" data-testid="bundle-problem">
        {say(product.problem)}
      </p>
      <ul className="mt-5 grid gap-5 @xl:grid-cols-3 @xl:gap-0 @xl:divide-x @xl:divide-shell-line rtl:@xl:divide-x-reverse">
        {product.benefits.map((benefit, index) => (
          <li key={benefit.title.fr} className="@xl:px-5 @xl:first:ps-0 @xl:last:pe-0" data-testid="bundle-benefit">
            <ProductTile icon={benefit.icon} index={index} />
            <h3 className="mt-3 text-[1.0625rem] leading-snug font-bold text-brand-navy">{say(benefit.title)}</h3>
            <p className="mt-1 text-[0.875rem] text-shell-muted">{say(benefit.body)}</p>
          </li>
        ))}
      </ul>
    </ProductSection>
  );
}

function UseCasesSection({ product }: { product: BundleProduct }) {
  const t = useDictionary();
  const say = useSay();
  return (
    <ProductSection id="use-cases" icon={Lightbulb} title={t.catalogue.bundle.useCases}>
      <ul className="grid gap-3 @xl:grid-cols-3">
        {product.useCases.map((use, index) => (
          <li key={use.title.fr} className="rounded-xl border border-shell-line p-4" data-testid="bundle-use-case">
            <ProductTile icon={use.icon} index={index + 1} className="size-9 [&_svg]:size-4" />
            <h3 className="mt-3 text-[0.9375rem] font-semibold text-brand-navy">{say(use.title)}</h3>
            <p className="mt-1 text-[0.8125rem] text-shell-muted">{say(use.body)}</p>
          </li>
        ))}
      </ul>
    </ProductSection>
  );
}

/** Every agent it includes, its role in a sentence — each its own page,
 * the whole row the way in. */
function AgentsSection({ bundle, offers }: { bundle: BundleOffer; offers: AddOns }) {
  const t = useDictionary();
  const w = t.catalogue.bundle;
  const say = useSay();
  const { format } = useLocale();
  const members = bundle.members ?? [];
  const sold = new Map(offers.agents.map((agent) => [agent.key, agent]));
  return (
    <ProductSection id="agents" icon={Users} title={fill(w.agents, { count: members.length })}>
      <p className="-mt-2 mb-4 text-[0.8125rem] text-shell-muted">{w.agentsLead}</p>
      <ul className="grid gap-3 @2xl:grid-cols-2" data-testid="bundle-agents">
        {members.map((member) => {
          const offer = member.agent ? sold.get(member.agent) : undefined;
          const market = offer ? marketOf(offer) : null;
          const title = member.agent ? agentTitle(t, member.agent, offer?.title ?? member.name) : member.name;
          const role = member.agent ? productOf(member.agent)?.promise : undefined;
          const summary = member.agent
            ? (t.catalogue.summaries as Record<string, string>)[member.agent] ?? offer?.summary
            : undefined;
          return (
            <li
              key={member.key}
              className={cn(
                "group relative flex gap-3 rounded-xl border border-shell-line p-4 transition-[border-color,box-shadow] duration-150 ease-[var(--ease-out)]",
                member.agent &&
                  "cursor-pointer [@media(hover:hover)_and_(pointer:fine)]:hover:border-brand-violet/40 has-[a:focus-visible]:border-brand-violet has-[a:focus-visible]:ring-3 has-[a:focus-visible]:ring-brand-violet/30",
              )}
              data-testid="bundle-agent"
              data-key={member.agent ?? member.key}
            >
              {market ? (
                <MarketTile
                  market={market}
                  label={(t.catalogue.markets as Record<string, string>)[market] ?? ""}
                  className="size-10"
                />
              ) : (
                <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-shell-canvas">
                  <Package className="size-4.5 text-shell-muted" aria-hidden="true" />
                </span>
              )}
              <div className="min-w-0 flex-1">
                <h3 className="text-[0.9375rem] font-semibold text-brand-navy group-hover:text-shell-nav-active">
                  {member.agent ? (
                    <Link
                      href={routes.capability(member.agent)}
                      className="outline-none after:absolute after:inset-0 after:rounded-xl"
                      data-testid="bundle-agent-open"
                    >
                      {title}
                    </Link>
                  ) : (
                    title
                  )}
                </h3>
                <p className="mt-1 line-clamp-3 text-[0.8125rem] text-shell-muted">
                  {role ? say(role) : summary ?? w.notBuilt}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                  {member.agent ? <AgentStateSaid agentKey={member.agent} /> : <Pill tone="neutral">{w.notBuilt}</Pill>}
                  {member.monthly_price !== null && member.monthly_price !== undefined ? (
                    <span className="text-shell-muted tabular-nums" data-testid="bundle-agent-price">
                      {fill(w.alone, { price: euros(member.monthly_price, format) })}
                    </span>
                  ) : null}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </ProductSection>
  );
}

/** Its price against its agents bought one by one — the saving said only
 * where it is computed from every agent's price today. */
function PricingSection({ bundle, offers }: { bundle: BundleOffer; offers: AddOns }) {
  const t = useDictionary();
  const w = t.catalogue.bundle;
  const { format } = useLocale();
  const saving = bundleSaving(bundle);
  const members = bundle.members ?? [];
  const titles = new Map(offers.agents.map((agent) => [agent.key, agentTitle(t, agent.key, agent.title)]));
  return (
    <ProductSection id="pricing" icon={Receipt} title={w.pricing}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[20rem] text-[0.875rem]" data-testid="bundle-pricing">
          <tbody className="divide-y divide-shell-line">
            {members.map((member) => (
              <tr key={member.key}>
                <th scope="row" className="py-2 pe-3 text-start font-normal text-brand-navy">
                  {member.agent ? (titles.get(member.agent) ?? member.name) : member.name}
                </th>
                <td className="py-2 text-end tabular-nums text-shell-muted">
                  {member.monthly_price !== null && member.monthly_price !== undefined
                    ? fill(w.alone, { price: euros(member.monthly_price, format) })
                    : w.aloneUnknown}
                </td>
              </tr>
            ))}
            {saving ? (
              <tr data-testid="bundle-separately">
                <th scope="row" className="py-2 pe-3 text-start font-semibold text-brand-navy">
                  {w.separately}
                </th>
                <td className="py-2 text-end font-semibold tabular-nums text-shell-muted line-through">
                  {fill(w.alone, { price: euros(saving.alone, format) })}
                </td>
              </tr>
            ) : null}
            <tr>
              <th scope="row" className="py-2 pe-3 text-start font-bold text-brand-navy">
                {w.inBundle}
              </th>
              <td className="py-2 text-end font-bold tabular-nums text-brand-navy" data-testid="bundle-pricing-total">
                {fill(w.alone, { price: euros(bundle.monthly_price, format) })}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p
        className={cn("mt-3 text-[0.875rem]", saving ? "font-semibold text-state-success" : "text-shell-muted")}
        data-testid="bundle-saving-said"
      >
        {saving
          ? fill(w.saving, { amount: euros(saving.amount, format), percent: saving.percent })
          : w.noSaving}
      </p>
      <p className="mt-1 text-xs text-shell-muted">
        {w.cadenceSaid[offers.interval]}
        {offers.provisional ? ` ${w.provisional}` : ""}
      </p>
    </ProductSection>
  );
}

function ChooseCard({
  bundle,
  offers,
  state,
  where,
}: {
  bundle: BundleOffer;
  offers: AddOns;
  state: BundleState | null;
  where: "top" | "side";
}) {
  const t = useDictionary();
  const w = t.catalogue.bundle;
  const { format } = useLocale();
  const tone = bundleTone(bundle.key);
  const saving = bundleSaving(bundle);
  return (
    <section
      aria-labelledby={`bundle-choose-${where}`}
      className="overflow-hidden rounded-2xl border border-shell-line bg-white"
      data-testid={where === "side" ? "bundle-choose" : "bundle-choose-top"}
    >
      <div className={cn("h-1.5 bg-linear-to-r", tone.band)} aria-hidden="true" />
      <div className="p-5">
        <h2 id={`bundle-choose-${where}`} className="text-lg font-bold text-brand-navy">
          {w.choose}
        </h2>
        {state !== "contract" ? (
          <>
            <p className="mt-3 flex flex-wrap items-baseline gap-x-1.5 gap-y-1">
              <span className="text-[2rem] leading-none font-bold tabular-nums text-brand-navy">
                {euros(bundle.monthly_price, format)}
              </span>
              <span className="text-[0.8125rem] text-shell-muted">{w.perMonth}</span>
            </p>
            {saving ? (
              <p className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                <span className="text-shell-muted line-through">{euros(saving.alone, format)}</span>
                <Pill tone="success">{fill(t.catalogue.offers.save, { percent: saving.percent })}</Pill>
              </p>
            ) : null}
            <p className="mt-2 text-xs text-shell-muted" data-testid="bundle-cadence">
              {w.cadenceSaid[offers.interval]}
            </p>
          </>
        ) : null}
        <div className="mt-4 flex flex-col gap-2.5">
          <BundleCta bundle={bundle} offers={offers} state={state} />
          <Link
            href={`${routes.capabilities()}#bundles`}
            className={cn(buttonVariants({ variant: "outline", size: "lg" }), "w-full justify-center")}
          >
            {w.back}
          </Link>
        </div>
      </div>
    </section>
  );
}

/** What this workspace may do with it — the same state as its card. */
function BundleCta({ bundle, offers, state }: { bundle: BundleOffer; offers: AddOns; state: BundleState | null }) {
  const t = useDictionary();
  const w = t.catalogue.bundle;
  const purchase = useBundlePurchase();
  const tone = bundleTone(bundle.key);
  const primary = cn(buttonVariants({ size: "lg" }), "w-full justify-center text-white", tone.button);
  const plan = offers.minimum_plan.charAt(0).toUpperCase() + offers.minimum_plan.slice(1);
  if (state === "owned") {
    return (
      <div className="flex flex-col gap-2" data-testid="bundle-cta" data-cta="owned">
        <span className="inline-flex h-11 items-center justify-center gap-2 rounded-lg bg-state-success/10 text-[0.875rem] font-semibold text-state-success">
          <CircleCheck className="size-4" aria-hidden="true" />
          {w.states.owned}
        </span>
        <p className="text-xs text-shell-muted">{w.ctas.ownedHint}</p>
        <Link href={routes.billing()} className={cn(buttonVariants({ variant: "outline", size: "lg" }), "w-full justify-center")}>
          {w.ctas.manage}
        </Link>
      </div>
    );
  }
  if (state === "option") {
    return (
      <div className="flex flex-col gap-1.5">
        <Button
          type="button"
          size="lg"
          className={primary}
          disabled={!purchase.may || purchase.pending}
          onClick={() => void purchase.buy(bundle, offers.interval)}
          data-testid="bundle-cta"
          data-cta={purchase.may ? "buy" : "ask"}
        >
          {w.ctas.buy}
        </Button>
        {purchase.may ? null : <p className="text-xs text-shell-muted">{w.ctas.askAdmin}</p>}
      </div>
    );
  }
  if (state === "upgrade") {
    return (
      <div className="flex flex-col gap-1.5">
        <Link href={routes.billingPlans()} className={primary} data-testid="bundle-cta" data-cta="upgrade">
          {w.ctas.upgrade}
        </Link>
        <p className="text-xs text-shell-muted">{fill(w.ctas.upgradeHint, { plan })}</p>
      </div>
    );
  }
  if (state === "contract") {
    return (
      <div className="flex flex-col gap-1.5" data-testid="bundle-cta" data-cta="contract">
        <p className="text-[0.875rem] text-brand-navy">{w.ctas.contractHint}</p>
        <Link href={routes.capabilities()} className={primary}>
          {w.ctas.allAgents}
        </Link>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1.5">
      <Button type="button" size="lg" className="w-full justify-center" disabled data-testid="bundle-cta" data-cta={state ?? "unknown"}>
        {state === "soon" ? w.states.soon : w.states.unavailable}
      </Button>
      <p className="text-xs text-shell-muted">{state === "soon" ? w.ctas.soonHint : w.ctas.unavailableHint}</p>
    </div>
  );
}
