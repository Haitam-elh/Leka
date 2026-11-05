"use client";

import {
  ArrowRight,
  ChevronRight,
  History,
  Network,
  Rocket,
} from "lucide-react";
import Link from "next/link";

import { cn } from "cn";
import { InstallAgent } from "@/components/capabilities/install-dialog";
import { MarketTile, marketOf } from "@/components/capabilities/market-mark";
import {
  agentStateOf,
  AgentStateSaid,
  Bundles,
  isEnterprise,
  useOrganisationName,
} from "@/components/capabilities/offers";
import { type TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { exactDate, timeAgo } from "@/components/knowledge/time";
import { buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { agentTitle } from "@/lib/agent-title";
import { euros } from "@/lib/billing";
import { useAddOns } from "@/lib/billing-queries";
import { useCapabilities } from "@/lib/capabilities-queries";
import { useEnvironment } from "@/lib/environment-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { recommend } from "@/lib/recommend-agents";
import { isConnected } from "@/lib/sources";
import { useSources } from "@/lib/sources-queries";
import { type Health, overallOf } from "@/lib/twin";

/**
 * The home's blocks of the sprint's mockup (LEKA-456), the question their
 * focus (LEKA-470): « Mon environnement » reduced to its state and its last
 * read, the way to the analyses already asked, the agents on sale. Every
 * figure is the API's; what is not known is said so
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
  const sources = useSources().data;
  const failing = sources?.filter((source) => source.status === "error").length ?? 0;
  // Nothing connected (2026-10-25): said neutral, in grey — never a state.
  const none = sources !== undefined && !sources.some(isConnected);
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
  const health: Health = none ? "unknown" : overall.health;
  const percent =
    overall.share !== null && health !== "unknown" ? Math.round(overall.share * 100) : null;
  const last = env.freshness?.last_read_at;
  return (
    <section
      className={cn(CARD, "p-4")}
      aria-labelledby="home-environment"
      data-testid="home-environment"
      data-health={health}
      data-sources={none ? "none" : undefined}
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
            {percent === null ? "-" : `${percent} %`}
          </span>
        </div>
        <div className="min-w-0 space-y-1.5">
          <Pill tone={HEALTH_TONE[health]} dot data-testid="home-health">
            {none ? w.noSource : w.health[health]}
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
      {/* The things « Inconnu » counts, one click away (LEKA-532). */}
      {(env.states?.unknown ?? 0) > 0 ? (
        <Link
          href={`${routes.environment()}?state=unknown`}
          className="mt-2 block rounded text-center text-xs font-medium text-brand-navy outline-none hover:underline focus-visible:ring-3 focus-visible:ring-brand-violet/40"
          data-testid="home-unknown"
        >
          {fill(w.unknownSee, { count: env.states?.unknown ?? 0 })}
        </Link>
      ) : null}
      {/* Its rule, its states, what would raise it: the diagnosis on Mon
          environnement, the same definition (LEKA-489, LEKA-532). */}
      <Link
        href={`${routes.environment()}?state=all`}
        className="mt-2 block rounded text-center text-xs text-shell-nav-active outline-none hover:underline focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        data-testid="home-health-explained"
      >
        {t.environment.overall.understand}
      </Link>
    </section>
  );
}

/** « Historique des analyses », under the question (LEKA-470): every
 * intention asked, on the list that already holds them. */
export function HistoryLink({ className }: { className?: string } = {}) {
  const t = useDictionary();
  return (
    <div className={cn("mt-2.5 flex items-center justify-end px-1", className)}>
      <Link
        href={routes.intentions()}
        className="inline-flex items-center gap-1.5 text-[0.8125rem] font-medium text-shell-nav-active transition-opacity duration-150 ease-[var(--ease-out)] hover:opacity-80 outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        data-testid="home-history"
      >
        <History className="size-3.5" aria-hidden="true" />
        {t.overview.home.history}
      </Link>
    </div>
  );
}

/** « Agents disponibles » (LEKA-470, its mockup): the agents on sale,
 * dense — six a row on a wide screen, four, three, two on a phone, twelve
 * at most (six on a phone) so no row is left half empty — each its domain,
 * its name, where this workspace stands with it in the marketplace's
 * words, its price only where there is one to pay. Nothing while nothing
 * is on sale.
 *
 * Each card is one target (LEKA-528): the whole of it opens the agent's
 * page, where it is described, bought or opened — no description, no
 * button of its own, nothing nested. Its title is the link (what a screen
 * reader names it), stretched over the card; the card shows the pointer
 * over it, the keyboard's focus and the press. */
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
            {isEnterprise(offers) ? w.agentsBodyContract : w.agentsBody}
          </p>
        </div>
        <Link href={routes.capabilities()} className={LINK}>
          {isEnterprise(offers) ? w.allAgentsOnly : w.allAgents}
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
                "group relative flex cursor-pointer flex-col p-3.5 transition-[border-color,box-shadow,scale] duration-150 ease-[var(--ease-out)]",
                "[@media(hover:hover)_and_(pointer:fine)]:hover:border-brand-violet/40 [@media(hover:hover)_and_(pointer:fine)]:hover:shadow-[0_6px_18px_-6px_rgba(7,17,67,0.14)]",
                "has-[a:focus-visible]:border-brand-violet has-[a:focus-visible]:ring-3 has-[a:focus-visible]:ring-brand-violet/30 motion-safe:has-[a:active]:scale-[0.98]",
                "max-md:nth-[n+3]:hidden md:max-lg:nth-[n+4]:hidden lg:max-xl:nth-[n+5]:hidden",
              )}
              data-testid="home-agent"
              data-key={agent.key}
              data-fit={fit ?? undefined}
            >
              <div className="flex items-center gap-2">
                <MarketTile market={market} label={marketName} />
                <span className="min-w-0 flex-1 truncate text-xs text-shell-muted" data-testid="home-agent-market">
                  {marketName}
                </span>
                {/* Said clickable without a button: the way in, brighter under
                    the pointer. Not on a phone: its domain's name needs the room. */}
                <ChevronRight
                  className="hidden size-4 shrink-0 text-shell-muted sm:block transition-[color,translate] duration-150 ease-[var(--ease-out)] rtl:-scale-x-100 group-hover:text-shell-nav-active motion-safe:group-hover:translate-x-0.5"
                  aria-hidden="true"
                />
              </div>
              <h3 className="mt-2.5 text-[0.875rem] leading-snug font-semibold text-brand-navy transition-colors duration-150 group-hover:text-shell-nav-active">
                <Link
                  href={routes.capability(agent.key)}
                  className="outline-none after:absolute after:inset-0 after:rounded-2xl"
                  data-testid="home-agent-open"
                >
                  {agentTitle(t, agent.key, agent.title)}
                </Link>
              </h3>
              {/* A source it reads is not connected yet: said, as what is
                  missing — what it works with needs no word. */}
              {fit === "to_connect" ? (
                <p className="mt-1 text-xs text-shell-muted" data-testid="home-agent-fit">
                  {w.fit.to_connect}
                </p>
              ) : null}
              <div className="mt-auto flex flex-wrap items-center justify-between gap-x-2 gap-y-1.5 pt-3">
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
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** The agents made for this organisation (2026-10-25), first on its home:
 * each one's card — what it does, the sources it reads, « Lancer ». Never
 * a price: it is not sold. */
export function DedicatedAgentsSection() {
  const t = useDictionary();
  const w = t.overview.home.dedicated;
  const offers = useAddOns().data;
  const organisation = useOrganisationName();
  const catalogue = useCapabilities({}).data;
  const keys = offers?.dedicated ?? [];
  if (!keys.length) return null;
  const summaries = t.catalogue.summaries as Record<string, string>;
  return (
    <section className="mt-8" aria-labelledby="home-dedicated" data-testid="home-dedicated">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="home-dedicated" className="text-lg font-bold tracking-[-0.01em] text-brand-navy">
            {w.title}
          </h2>
          {organisation ? (
            <p className="mt-1 text-[0.875rem] text-shell-muted">{fill(w.lead, { organisation })}</p>
          ) : null}
        </div>
        {/* All of them, on the agents' page, their section (2026-10-25). */}
        <Link
          href={`${routes.capabilities()}#dedicated`}
          className={LINK}
          data-testid="home-dedicated-all"
        >
          {w.seeAll}
          <ArrowRight className="rtl:-scale-x-100 size-4" aria-hidden="true" />
        </Link>
      </div>
      {/* One line each (2026-10-25, Karim: « ça prend la moitié de la page
          pour rien »): what it is, what it does, its actions. */}
      <ul className="mt-3 flex flex-col gap-2">
        {keys.map((key) => {
          const capability = catalogue?.find((c) => c.key === key);
          return (
            <li
              key={key}
              className={cn(CARD, "flex flex-wrap items-center gap-x-4 gap-y-2 border-brand-violet/30 px-4 py-3")}
              data-testid="home-dedicated-agent"
              data-key={key}
            >
              <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-brand-violet-soft text-shell-nav-active">
                <Network className="size-4.5" aria-hidden="true" />
              </span>
              <div className="min-w-0 flex-1 basis-60">
                <h3 className="text-[0.9375rem] font-semibold text-brand-navy">
                  <Link href={routes.capability(key)} className="rounded hover:underline">
                    {agentTitle(t, key, capability?.title ?? key)}
                  </Link>
                </h3>
                <p className="truncate text-[0.8125rem] text-shell-muted" title={summaries[key] ?? capability?.summary ?? ""}>
                  {summaries[key] ?? capability?.summary ?? ""}
                </p>
              </div>
              {/* Its actions wrap on a phone, never wider than the screen. */}
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <AgentStateSaid agentKey={key} />
                <Link
                  // The architect on a Confluence space (2026-10-25): its perimeter chosen first.
                  href={key === "application-architecture" ? routes.architect() : `${routes.capability(key)}#use`}
                  className={buttonVariants({ size: "sm" })}
                  data-testid="home-dedicated-launch"
                >
                  <Rocket aria-hidden="true" />
                  {w.launch}
                </Link>
                {/* On the organisation's own machines (2026-10-25). */}
                <InstallAgent agentKey={key} />
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
