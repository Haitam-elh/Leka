"use client";

import {
  ArrowRight,
  ChevronRight,
  History,
} from "lucide-react";
import Link from "next/link";

import { cn } from "cn";
import { MarketTile, marketOf } from "@/components/capabilities/market-mark";
import { AgentCardAction, agentStateOf, AgentStateSaid, Bundles } from "@/components/capabilities/offers";
import { type TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { StatusPill } from "@/components/intentions/intentions-list";
import { exactDate, timeAgo } from "@/components/knowledge/time";
import { routes } from "@/config/routes";
import { euros } from "@/lib/billing";
import { useAddOns } from "@/lib/billing-queries";
import { useCapabilities } from "@/lib/capabilities-queries";
import { useEnvironment } from "@/lib/environment-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { useIntentions } from "@/lib/intentions/queries";
import { recommend } from "@/lib/recommend-agents";
import { useSources } from "@/lib/sources-queries";
import { type Health, overallOf } from "@/lib/twin";

/**
 * The home's blocks of the sprint's mockup (LEKA-456), the question their
 * focus (LEKA-470): « Mon environnement » reduced to its state and its last
 * read, the way to the analyses already asked, the agents on sale, the
 * latest analyses. Every figure is the API's; what is not known is said so
 * — never « 100 % Stable » by default.
 */

const CARD = "rounded-2xl border border-shell-line bg-white";

const LINK =
  "inline-flex items-center gap-1.5 rounded text-sm font-medium text-brand-violet outline-none hover:underline focus-visible:ring-3 focus-visible:ring-brand-violet/40";

/** Its word's colour: the same as its ring's. */
const HEALTH_TONE: Record<Health, TileTone> = {
  unknown: "neutral",
  stale: "warning",
  incident: "danger",
  partial: "warning",
  stable: "success",
};

/** The state the environment card may claim, from what is measured. */
const RING: Record<Health, string> = {
  unknown: "text-shell-line",
  stale: "text-state-warning",
  incident: "text-state-danger",
  partial: "text-state-warning",
  stable: "text-state-success",
};

/** « Mon environnement », top right (LEKA-470): its state as measured —
 * the gauge, the word for it — and when its sources were last read, the
 * moment itself and how long ago. The rest is its page's, one click away. */
export function EnvironmentCard() {
  const t = useDictionary();
  const w = t.overview.home;
  const { format } = useLocale();
  const env = useEnvironment().data;
  const failing = useSources().data?.filter((source) => source.status === "error").length ?? 0;
  if (!env) {
    return (
      <div
        className={cn(CARD, "h-36 animate-pulse bg-shell-canvas")}
        aria-hidden="true"
      />
    );
  }
  // The page's own rule (LEKA-468): the same figure on both screens.
  const overall = overallOf(env);
  const { health } = overall;
  const percent =
    overall.share !== null && health !== "unknown" ? Math.round(overall.share * 100) : null;
  const last = env.freshness?.last_read_at;
  return (
    <section
      className={cn(CARD, "p-4")}
      aria-labelledby="home-environment"
      data-testid="home-environment"
      data-health={health}
    >
      <Link
        href={routes.environment()}
        className="flex items-center justify-between rounded outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40"
      >
        <h2
          id="home-environment"
          className="text-[0.9375rem] font-semibold text-brand-navy"
        >
          {w.environment}
        </h2>
        <ChevronRight
          className="rtl:-scale-x-100 size-4 text-shell-muted"
          aria-hidden="true"
        />
      </Link>
      <div className="mt-3 flex items-center gap-3">
        <div className="relative size-14 shrink-0">
          <svg
            viewBox="0 0 36 36"
            className="size-full -rotate-90"
            aria-hidden="true"
          >
            <circle
              cx="18"
              cy="18"
              r="15.5"
              fill="none"
              strokeWidth="3.5"
              className="stroke-shell-canvas"
            />
            <circle
              cx="18"
              cy="18"
              r="15.5"
              fill="none"
              strokeWidth="3.5"
              strokeLinecap="round"
              className={cn("stroke-current", RING[health])}
              strokeDasharray={`${((percent ?? 0) / 100) * 97.4} 97.4`}
            />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-[0.8125rem] font-bold tabular-nums text-brand-navy">
            {percent === null ? "—" : `${percent} %`}
          </span>
        </div>
        <div className="min-w-0 space-y-1.5">
          <Pill tone={HEALTH_TONE[health]} dot data-testid="home-health">
            {w.health[health]}
          </Pill>
          <p
            className="text-[0.6875rem] leading-snug text-shell-muted"
            data-testid="home-last-sync"
          >
            <span className="block">{w.lastSync}</span>
            {last ? (
              <>
                <span className="block font-medium text-brand-navy">
                  {timeAgo(t, last)}
                </span>
                <time className="block" dateTime={last}>
                  {exactDate(format, last)}
                </time>
              </>
            ) : (
              <span className="block">{w.neverSynced}</span>
            )}
          </p>
        </div>
      </div>
      {failing > 0 ? (
        <Link
          href={routes.sources()}
          className="mt-3 block rounded text-center text-xs font-medium text-state-danger outline-none hover:underline focus-visible:ring-3 focus-visible:ring-brand-violet/40"
          data-testid="home-sources-failing"
        >
          {fill(w.sourcesFailing, { count: failing })}
        </Link>
      ) : null}
    </section>
  );
}

/** « Historique des analyses », under the question (LEKA-470): every
 * intention asked, on the list that already holds them. */
export function HistoryLink() {
  const t = useDictionary();
  return (
    <div className="mt-4 flex justify-center">
      <Link
        href={routes.intentions()}
        className="inline-flex items-center gap-2 rounded-xl border border-brand-violet/40 bg-white px-4 py-2 text-[0.875rem] font-medium text-shell-nav-active transition-colors outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        data-testid="home-history"
      >
        <History className="size-4" aria-hidden="true" />
        {t.overview.home.history}
      </Link>
    </div>
  );
}

/** « Agents disponibles » (LEKA-470, its mockup): the agents on sale,
 * dense — six a row on a wide screen, four, three, two on a phone, twelve
 * at most (six on a phone) so no row is left half empty — each its name,
 * what it does, where this workspace stands with it in the marketplace's
 * words, its price only where there is one to pay — an option not bought —
 * and there its « + » to buy it. Nothing while nothing is on sale. */
export function AgentsSection() {
  const t = useDictionary();
  const w = t.overview.home;
  const { format } = useLocale();
  const offers = useAddOns().data;
  // What each needs, to recommend what works here first (LEKA-488).
  const catalogue = useCapabilities({}).data;
  if (!offers?.available || offers.agents.length === 0) return null;
  const row = recommend(offers.agents, (key) => agentStateOf(offers, key), catalogue, 6);
  return (
    <section
      className="mt-10"
      aria-labelledby="home-agents"
      data-testid="home-agents"
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2
            id="home-agents"
            className="text-xl font-bold tracking-[-0.01em] text-brand-navy"
          >
            {w.agents}
          </h2>
          <p className="mt-1 text-[0.875rem] text-shell-muted">
            {w.agentsBody}
          </p>
        </div>
        <Link href={routes.capabilities()} className={LINK}>
          {w.allAgents}
          <ArrowRight className="rtl:-scale-x-100 size-4" aria-hidden="true" />
        </Link>
      </div>
      <ul
        className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6"
        data-testid="home-agents-grid"
      >
        {/* One row, at every width: as many as its columns. */}
        {row.map(({ agent, fit }) => {
          // Its domain, drawn as in the marketplace and its bundles (LEKA-493).
          const market = marketOf(agent);
          const marketName = (t.catalogue.markets as Record<string, string>)[market] ?? market;
          // Its price wherever it is to pay for — bought, or with a plan above (LEKA-497).
          const state = agentStateOf(offers, agent.key);
          const payable = state === "option" || state === "upgrade";
          return (
            <li
              key={agent.key}
              className={cn(
                CARD,
                "relative flex flex-col p-3.5 hover:border-brand-violet/40 max-md:nth-[n+3]:hidden md:max-lg:nth-[n+4]:hidden lg:max-xl:nth-[n+5]:hidden",
              )}
              data-testid="home-agent"
              data-key={agent.key}
              data-fit={fit ?? undefined}
            >
              <div className="flex items-center gap-2">
                <MarketTile market={market} label={marketName} />
                <span className="min-w-0 truncate text-xs text-shell-muted" data-testid="home-agent-market">
                  {marketName}
                </span>
              </div>
              <h3 className="mt-2.5 text-[0.875rem] leading-snug font-semibold text-brand-navy">
                {/* The whole card opens its page (LEKA-497); its action stays its own. */}
                <Link
                  href={routes.capability(agent.key)}
                  className="rounded outline-none after:absolute after:inset-0 after:rounded-2xl hover:underline focus-visible:ring-3 focus-visible:ring-brand-violet/40"
                  data-testid="home-agent-open"
                >
                  {agent.title}
                </Link>
              </h3>
              <p className="mt-1 line-clamp-2 flex-1 text-xs text-shell-muted">
                {(t.catalogue.summaries as Record<string, string>)[agent.key] ?? agent.summary}
              </p>
              {/* Why it is here: what it reads, against what is connected. */}
              {fit === "connected" || fit === "to_connect" ? (
                <p className="mt-2 text-xs text-shell-muted" data-testid="home-agent-fit">
                  {w.fit[fit]}
                </p>
              ) : null}
              <div className="mt-3 flex flex-wrap items-center justify-between gap-x-2 gap-y-1.5">
                <AgentStateSaid agentKey={agent.key} />
                {payable ? (
                  <span
                    className="text-xs font-semibold whitespace-nowrap tabular-nums text-brand-navy"
                    data-testid="home-agent-price"
                  >
                    {euros(agent.monthly_price, format)}
                    <span className="font-normal text-shell-muted">
                      {" "}
                      {t.catalogue.offers.monthHt}
                    </span>
                  </span>
                ) : null}
              </div>
              <div className="mt-2.5">
                <AgentCardAction agentKey={agent.key} />
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** The bundles, lower on the page (LEKA-470, its mockup): the
 * marketplace's own cards — their price, their saving, « Bientôt
 * disponible » where one is not on sale. No banner, no second link: the one
 * to the agents and bundles is above. */
export function HomeBundles() {
  return (
    <div className="mt-10" data-testid="home-bundles-cards">
      <Bundles />
    </div>
  );
}

/** « Dernières analyses »: the four latest intentions, where each stands. */
export function LatestAnalyses() {
  const t = useDictionary();
  const w = t.overview.home;
  const list = useIntentions(null, "");
  const rows = list.data?.pages.flatMap((page) => page.data).slice(0, 4) ?? [];
  if (list.isPending || rows.length === 0) return null;
  return (
    <section
      className="mt-10"
      aria-labelledby="home-latest"
      data-testid="home-latest"
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2
            id="home-latest"
            className="text-xl font-bold tracking-[-0.01em] text-brand-navy"
          >
            {w.latest}
          </h2>
          <p className="mt-1 text-[0.875rem] text-shell-muted">
            {w.latestBody}
          </p>
        </div>
        <Link href={routes.intentions()} className={LINK}>
          {w.allHistory}
          <ArrowRight className="rtl:-scale-x-100 size-4" aria-hidden="true" />
        </Link>
      </div>
      <ul className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {rows.map((intention) => (
          <li key={intention.id}>
            <Link
              href={routes.intention(intention.id)}
              className={cn(
                CARD,
                "flex h-full flex-col gap-2 p-4 outline-none hover:border-brand-violet/40 focus-visible:ring-3 focus-visible:ring-brand-violet/40",
              )}
              data-testid="home-latest-item"
            >
              <span className="flex items-start justify-between gap-2">
                <span className="line-clamp-2 font-semibold text-brand-navy">
                  {intention.title}
                </span>
                <span className="shrink-0 text-xs text-shell-muted">
                  {timeAgo(t, intention.updated_at)}
                </span>
              </span>
              <span>
                <StatusPill
                  status={intention.status}
                  journey={intention.journey}
                />
              </span>
              {intention.summary ? (
                <span className="line-clamp-2 text-[0.8125rem] text-shell-muted">
                  {intention.summary}
                </span>
              ) : null}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
