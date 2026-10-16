"use client";

import {
  ArrowRight,
  Bug,
  ChartColumn,
  ChevronRight,
  Clock3,
  Code2,
  FileText,
  Network,
  Package,
  ShieldCheck,
  UserRound,
  CircleCheck,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";

import { cn } from "cn";
import { AgentPrice } from "@/components/capabilities/offers";
import { StatusPill } from "@/components/intentions/intentions-list";
import { timeAgo } from "@/components/knowledge/time";
import { routes } from "@/config/routes";
import { useAddOns } from "@/lib/billing-queries";
import { useEnvironment } from "@/lib/environment-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { useIntentions } from "@/lib/intentions/queries";
import { isConnected } from "@/lib/sources";
import { useSources } from "@/lib/sources-queries";

/**
 * The home's blocks of the sprint's mockup (LEKA-456): « Mon environnement »
 * beside the question, the agents on sale, the bundles, the latest
 * analyses. Every figure is the API's; what is not known is said so —
 * never « 100 % Stable » by default.
 */

const CARD = "rounded-2xl border border-shell-line bg-white";

const LINK =
  "inline-flex items-center gap-1.5 rounded text-sm font-medium text-brand-violet outline-none hover:underline focus-visible:ring-3 focus-visible:ring-brand-violet/40";

/** The state the environment card may claim, from what is measured. */
export type Health = "unknown" | "stale" | "incident" | "partial" | "stable";

export function healthOf(env: {
  services: number;
  services_unknown?: number;
  incidents_open: number;
  sources?: readonly unknown[];
  freshness?: { late: boolean } | null;
}): Health {
  if (!env.sources?.length || env.services === 0) return "unknown";
  if (env.freshness?.late) return "stale";
  if (env.incidents_open > 0) return "incident";
  if ((env.services_unknown ?? 0) > 0) return "partial";
  return "stable";
}

const RING: Record<Health, string> = {
  unknown: "text-shell-line",
  stale: "text-state-warning",
  incident: "text-state-danger",
  partial: "text-state-warning",
  stable: "text-state-success",
};

/** « Mon environnement », top right: its state as measured, its sources,
 * when they were last read, the services LEKA knows. */
export function EnvironmentCard() {
  const t = useDictionary();
  const w = t.overview.home;
  const env = useEnvironment().data;
  // Connected only, as Sources counts them: a draft whose token was refused is not.
  const connected = useSources().data?.filter(isConnected).length;
  if (!env) {
    return (
      <div
        className={cn(CARD, "h-64 animate-pulse bg-shell-canvas")}
        aria-hidden="true"
      />
    );
  }
  const health = healthOf(env);
  const known = env.services - (env.services_unknown ?? 0);
  const percent =
    env.services > 0 && health !== "unknown"
      ? Math.round((env.services_operational / env.services) * 100)
      : null;
  const last = env.freshness?.last_read_at;
  return (
    <section
      className={cn(CARD, "p-6")}
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
          className="text-lg font-semibold text-brand-navy"
        >
          {w.environment}
        </h2>
        <ChevronRight
          className="rtl:-scale-x-100 size-5 text-shell-muted"
          aria-hidden="true"
        />
      </Link>
      <div className="mt-4 flex items-center gap-5">
        <div className="relative size-[86px] shrink-0">
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
          <span className="absolute inset-0 flex items-center justify-center text-lg font-bold text-brand-navy">
            {percent === null ? "—" : `${percent} %`}
          </span>
        </div>
        <div className="min-w-0">
          <p
            className={cn(
              "text-2xl font-semibold",
              health === "stable" ? "text-state-success" : "text-brand-navy",
            )}
            data-testid="home-health"
          >
            {w.health[health]}
          </p>
          <p className="mt-1 text-[0.8125rem] text-shell-muted">
            {health === "incident"
              ? fill(w.incidents, { count: env.incidents_open })
              : health === "partial"
                ? fill(w.measured, { known, total: env.services })
                : w.healthHint[health]}
          </p>
        </div>
      </div>
      <dl className="mt-5 grid grid-cols-3 divide-x divide-shell-line border-t border-shell-line pt-4 text-center rtl:divide-x-reverse">
        <div>
          <UserRound
            className="mx-auto size-5 text-brand-navy"
            aria-hidden="true"
          />
          <dd className="mt-1 text-lg font-semibold text-brand-navy">
            {connected ?? env.sources?.length ?? 0}
          </dd>
          <dt className="text-xs text-shell-muted">
            {fill(w.sources, { count: connected ?? env.sources?.length ?? 0 })}
          </dt>
        </div>
        <div>
          <Clock3
            className="mx-auto size-5 text-brand-navy"
            aria-hidden="true"
          />
          <dd className="mt-1 text-sm font-semibold text-brand-navy">
            {last ? timeAgo(t, last) : "—"}
          </dd>
          <dt className="text-xs text-shell-muted">{w.lastSync}</dt>
        </div>
        <div>
          <CircleCheck
            className="mx-auto size-5 text-brand-navy"
            aria-hidden="true"
          />
          <dd className="mt-1 text-lg font-semibold text-brand-navy">
            {env.services}
          </dd>
          <dt className="text-xs text-shell-muted">{w.services}</dt>
        </div>
      </dl>
    </section>
  );
}

/** An agent's tile: its category's mark, the catalogue's own colours. */
const CATEGORY_MARK: Record<string, { icon: LucideIcon; tone: string }> = {
  code: { icon: Code2, tone: "bg-violet-100 text-violet-600" },
  architecture: { icon: Network, tone: "bg-sky-100 text-sky-600" },
  security: { icon: ShieldCheck, tone: "bg-emerald-100 text-emerald-600" },
  incident: { icon: Bug, tone: "bg-rose-100 text-rose-600" },
  performance: { icon: ChartColumn, tone: "bg-amber-100 text-amber-600" },
  documentation: { icon: FileText, tone: "bg-blue-100 text-blue-600" },
};

function markOf(category: string) {
  const key = Object.keys(CATEGORY_MARK).find((k) =>
    category.toLowerCase().includes(k),
  );
  return CATEGORY_MARK[key ?? "code"];
}

/** « Agents disponibles »: six of the agents on sale, their price and
 * where this workspace stands — bought, to buy, a plan above — as the
 * catalogue says. Nothing while nothing is on sale. */
export function AgentsSection() {
  const t = useDictionary();
  const w = t.overview.home;
  const offers = useAddOns().data;
  if (!offers?.available || offers.agents.length === 0) return null;
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
            className="text-2xl font-bold tracking-[-0.01em] text-brand-navy"
          >
            {w.agents}
          </h2>
          <p className="mt-1 text-[0.9375rem] text-shell-muted">
            {w.agentsBody}
          </p>
        </div>
        <Link href={routes.capabilities()} className={LINK}>
          {w.allAgents}
          <ArrowRight className="rtl:-scale-x-100 size-4" aria-hidden="true" />
        </Link>
      </div>
      <ul className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-6">
        {offers.agents.slice(0, 6).map((agent) => {
          const { icon: Icon, tone } = markOf(agent.category);
          return (
            <li
              key={agent.key}
              className={cn(CARD, "flex flex-col p-4")}
              data-testid="home-agent"
            >
              <span
                className={cn(
                  "flex size-11 items-center justify-center rounded-xl",
                  tone,
                )}
              >
                <Icon className="size-5" aria-hidden="true" />
              </span>
              <h3 className="mt-3 font-semibold text-brand-navy">
                {agent.title}
              </h3>
              <p className="mt-1 line-clamp-2 flex-1 text-[0.8125rem] text-shell-muted">
                {(t.catalogue.summaries as Record<string, string>)[agent.key] ?? agent.summary}
              </p>
              <div className="mt-3">
                <AgentPrice agentKey={agent.key} />
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** « Bundles LEKA »: what they are, and the way to them. */
export function BundlesBanner() {
  const t = useDictionary();
  const w = t.overview.home;
  const offers = useAddOns().data;
  if (!offers?.available || offers.bundles.length === 0) return null;
  return (
    <section
      className={cn(
        CARD,
        "mt-6 flex flex-wrap items-center gap-4 bg-shell-canvas/60 p-5",
      )}
      aria-labelledby="home-bundles"
      data-testid="home-bundles"
    >
      <span className="flex size-14 items-center justify-center rounded-xl bg-brand-violet text-white">
        <Package className="size-6" aria-hidden="true" />
      </span>
      <div className="min-w-0 flex-1">
        <h2 id="home-bundles" className="text-lg font-semibold text-brand-navy">
          {w.bundles}
        </h2>
        <p className="text-[0.875rem] text-shell-muted">
          {fill(w.bundlesBody, { count: offers.bundles.length })}
        </p>
      </div>
      <Link
        href={`${routes.capabilities()}#bundles`}
        className="inline-flex items-center gap-2 rounded-lg border border-brand-violet/40 bg-white px-4 py-2 text-sm font-medium text-brand-violet outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
      >
        {w.discoverBundles}
        <ArrowRight className="rtl:-scale-x-100 size-4" aria-hidden="true" />
      </Link>
    </section>
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
            className="text-2xl font-bold tracking-[-0.01em] text-brand-navy"
          >
            {w.latest}
          </h2>
          <p className="mt-1 text-[0.9375rem] text-shell-muted">
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
