"use client";

import { Sparkle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { cn } from "cn";
import { items } from "@/components/approvals/items";
import { CompactIntentionComposer } from "@/components/intentions/compact-composer";
import { FirstStepsCard } from "@/components/overview/first-steps";
import {
  AgentsSection,
  DedicatedAgentsSection,
  EnvironmentCard,
  HistoryLink,
  HomeBundles,
} from "@/components/overview/home-sections";
import { PageContainer } from "@/components/shell/page-container";
import { useSourceLock } from "@/components/sources/source-lock";
import { useCurrentUser } from "@/components/shell/shell-provider";
import { timeAgo } from "@/components/knowledge/time";
import {
  askAbout,
  intentionHref,
  twinHow,
} from "@/components/environment/twin";
import { routes } from "@/config/routes";
import { fill } from "@/lib/i18n/dictionaries";
import { useConflicts } from "@/lib/conflicts-queries";
import { useDecisionQueue } from "@/lib/decisions-queries";
import { useCandidates } from "@/lib/enrichment-queries";
import {
  useEnvironment,
  useWorkingNow,
} from "@/lib/environment-queries";
import { byState, TROUBLE } from "@/lib/twin";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { type Source, sourceTone, sources as sourcesApi } from "@/lib/sources";

/**
 * The overview: Studio d'Intention.
 *
 * Unified around the intention composer and action: the greeting and
 * environment status sit at the top as a discrete chapeau, the operational
 * ribbon brings vital alerts and work under way directly under the composer,
 * followed by agents and bundles. The analyses asked are on the Intentions
 * page, the link under the composer (LEKA-560).
 */

type Load =
  | { status: "loading" }
  | { status: "failed" }
  | { status: "ready"; sources: Source[] };

function useOverviewData(): Load {
  const [load, setLoad] = useState<Load>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function run() {
      try {
        const { data: list } = await sourcesApi.list();
        if (!cancelled) setLoad({ status: "ready", sources: list });
      } catch {
        if (!cancelled) setLoad({ status: "failed" });
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, []);

  return load;
}

// ── Formatting ──────────────────────────────────────────────────────────────

function intlLocale(locale: string): string {
  return locale;
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// ── Studio chapeau ──────────────────────────────────────────────────────────

function GreetingChapeau({ load }: { load: Load }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const user = useCurrentUser();
  const name =
    user?.first_name?.trim() || capitalise(user?.email.split("@")[0] ?? "");
  const today = capitalise(
    new Intl.DateTimeFormat(intlLocale(locale), {
      weekday: "long",
      day: "numeric",
      month: "long",
    }).format(new Date()),
  );

  const environment = useEnvironment();
  const env = environment.data;
  let status = "";
  let tone: "success" | "warning" | "danger" | "neutral" = "neutral";
  if (load.status === "failed") {
    status = t.overview.loadFailed;
    tone = "danger";
  } else if (load.status === "ready") {
    const needing = load.sources.filter((source) =>
      ["attention", "error"].includes(sourceTone(source)),
    ).length;
    const trouble =
      (env?.states?.unavailable ?? 0) + (env?.states?.degraded ?? 0);
    if (load.sources.length === 0) {
      status = t.overview.statusNoSources;
      tone = "neutral";
    } else if (trouble > 0) {
      status = fill(t.overview.twin.statusTrouble, { count: trouble });
      tone = "danger";
    } else if (env?.freshness?.late) {
      status = t.overview.twin.statusLate;
      tone = "warning";
    } else if (needing > 0) {
      status = fill(t.overview.statusAttention, { count: needing });
      tone = "warning";
    } else {
      status = t.overview.statusSynced;
      tone = "success";
    }
  }

  const TONE_CLASSES = {
    success: "text-state-success",
    warning: "text-state-warning",
    danger: "text-state-danger",
    neutral: "text-shell-muted",
  };
  const DOT_CLASSES = {
    success: "bg-state-success",
    warning: "bg-state-warning",
    danger: "bg-state-danger",
    neutral: "bg-shell-muted",
  };

  return (
    <div
      className="inline-flex flex-wrap items-center gap-2 rounded-full border border-shell-line bg-shell-canvas px-3 py-1 text-xs font-medium text-shell-muted"
      data-testid="greeting-chapeau"
    >
      <h2 className="inline text-xs font-medium text-shell-muted">
        {fill(t.overview.greeting, { name })}
      </h2>
      <span className="opacity-50" aria-hidden="true">
        ·
      </span>
      <span>{today}</span>
      {status ? (
        <>
          <span className="opacity-50" aria-hidden="true">
            ·
          </span>
          <span
            className={cn(
              "inline-flex items-center gap-1.5 font-semibold",
              TONE_CLASSES[tone],
            )}
          >
            <span
              className={cn("size-1.5 rounded-full", DOT_CLASSES[tone])}
              aria-hidden="true"
            />
            {status}
          </span>
        </>
      ) : null}
    </div>
  );
}

// ── Operational Ribbon (« En ce moment ») ───────────────────────────────────

function OperationalRibbon() {
  const t = useDictionary();
  const w = t.overview.twin;
  const liveWords = t.overview.live;
  const steps = liveWords.steps as Record<string, string>;
  const { data: workData } = useWorkingNow();
  const work = workData ?? [];

  const proposed = useCandidates("proposed");
  const open = useConflicts("open");
  const waiting = useDecisionQueue("proposed");
  const approvalItems = items(
    proposed.data?.data ?? [],
    open.data?.data ?? [],
    waiting.data?.data ?? [],
  );
  const approvalsCount = approvalItems.length;

  const environment = useEnvironment();
  const env = environment.data;
  const trouble = byState(
    (env?.nodes ?? []).filter((n) => n.twin && TROUBLE.has(n.twin.state)),
  );

  const hasItems = work.length > 0 || approvalsCount > 0 || trouble.length > 0;

  if (!hasItems) return null;

  return (
    <div
      className="mt-4 flex items-center gap-3 overflow-x-auto rounded-[14px] border border-shell-line bg-white px-3.5 py-2.5 shadow-[0_1px_3px_rgba(7,17,67,0.02)]"
      data-testid="operational-ribbon"
    >
      <div className="flex shrink-0 items-center gap-1.5 border-r border-shell-line pe-3 text-[0.6875rem] font-bold tracking-wider text-shell-muted uppercase">
        {t.overview.ribbon.label}
      </div>
      <div className="flex min-w-0 flex-1 items-center gap-3">
        {work.slice(0, 2).map((item, index) => (
          <Link
            key={`work-${item.kind}-${item.href}-${index}`}
            href={item.href}
            className="inline-flex min-w-0 items-center gap-2 rounded-lg bg-shell-canvas px-2 py-1 text-xs whitespace-nowrap transition-colors duration-150 ease-[var(--ease-out)] hover:bg-brand-violet-soft/60"
            data-testid="live-work-item"
            data-kind={item.kind}
          >
            <span
              className="relative flex size-2 shrink-0 items-center justify-center"
              aria-hidden="true"
            >
              <span className="size-1.5 rounded-full bg-brand-violet transition-opacity duration-200 ease-[var(--ease-out)]" />
            </span>
            <span className="max-w-[200px] truncate font-semibold text-brand-navy">
              {item.title}
            </span>
            <span className="text-shell-muted">
              · {steps[item.step] ?? item.step}
              {item.since ? ` · ${timeAgo(t, item.since).toLowerCase()}` : ""}
            </span>
          </Link>
        ))}
        {approvalsCount > 0 ? (
          <Link
            href={routes.approvals()}
            className="inline-flex min-w-0 items-center gap-2 rounded-lg bg-shell-canvas px-2 py-1 text-xs whitespace-nowrap transition-colors duration-150 ease-[var(--ease-out)] hover:bg-brand-violet-soft/60"
            data-testid="ribbon-approvals"
          >
            <Sparkle
              className="size-3.5 shrink-0 fill-brand-violet text-brand-violet"
              aria-hidden="true"
            />
            <span className="font-semibold text-brand-navy">
              {fill(t.approvals.overview.waiting, { count: approvalsCount })}
            </span>
            <span className="font-semibold text-shell-nav-active hover:underline">
              {t.overview.ribbon.examine}
            </span>
          </Link>
        ) : null}
        {trouble.slice(0, 2).map((node) => (
          <div
            key={`trouble-${node.id}`}
            className="inline-flex min-w-0 items-center gap-2 rounded-lg bg-shell-canvas px-2 py-1 text-xs whitespace-nowrap"
            data-testid="ribbon-trouble"
            data-state={node.twin?.state}
          >
            <span className="inline-flex items-center gap-1 rounded-full bg-state-warning-soft px-1.5 py-0.5 text-[0.6875rem] font-semibold text-state-warning">
              <span
                className="size-1.5 rounded-full bg-state-warning"
                aria-hidden="true"
              />
              {t.overview.ribbon.alert}
            </span>
            <span className="font-semibold text-brand-navy">{node.name}</span>
            {node.twin ? (
              <span className="text-shell-muted">· {twinHow(t, node.twin)}</span>
            ) : null}
            {node.twin ? (
              <Link
                href={intentionHref(
                  askAbout(t, node.name, node.twin.state),
                )}
                className="font-semibold text-shell-nav-active hover:underline"
              >
                {w.analyse}
              </Link>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── The page ───────────────────────────────────────────────────────────────

export function Overview() {
  const load = useOverviewData();
  const locked = useSourceLock();

  return (
    <PageContainer>
      <div className="grid items-start gap-6 pt-4 xl:grid-cols-[16rem_minmax(0,1fr)_16rem] xl:gap-8 xl:pb-5">
        <div className="min-w-0 xl:col-start-2 xl:row-start-1" data-testid="home-focus">
          {/* The greeting level with « Mon environnement »'s top, the question
              right under it: no empty band in the hero (LEKA-560). */}
          <div className="mb-6 flex justify-center xl:mb-8">
            <GreetingChapeau load={load} />
          </div>
          <CompactIntentionComposer />
          <HistoryLink />
          <OperationalRibbon />
          {load.status === "ready" && !locked ? (
            <FirstStepsCard sources={load.sources} />
          ) : null}
        </div>
        <div className="mx-auto w-full max-w-sm xl:col-start-3 xl:row-start-1 xl:max-w-none">
          <EnvironmentCard />
        </div>
      </div>
      <DedicatedAgentsSection />
      <AgentsSection />
      <HomeBundles />
    </PageContainer>
  );
}
