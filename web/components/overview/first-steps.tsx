"use client";

import { CircleCheck, TriangleAlert, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { cn } from "cn";
import { ExploreDemoButton } from "@/components/demo/demo";
import { useInDemo } from "@/components/demo/in-demo";
import { buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { useEnterprise } from "@/lib/contract";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { useIntentionCounts } from "@/lib/intentions/queries";
import {
  CATEGORY_ORDER,
  type ConnectorCategory,
  isConnected,
  KIND_CATEGORY,
  type Source,
} from "@/lib/sources";

/**
 * « Premiers pas » — what a new workspace needs to get a first useful
 * answer (LEKA-445), on the overview, above nothing and blocking nothing:
 * the composer stays where it is, the card can be put away, and it goes by
 * itself once a source is read and a first question asked.
 *
 * Where the workspace stands is read from its sources, never assumed:
 *
 *   empty      nothing connected
 *   connected  connected, never read yet
 *   syncing    a first read under way
 *   failed     nothing read, a source failing — its cause and what to do
 *   ready      at least one source read
 *
 * A failing source is said with its cause and remedy whatever the stage.
 * The first question is asked in the bar below, in one's own words — no
 * example on the home (LEKA-470); until something is read, it is said that
 * LEKA cannot answer yet.
 */

export type Stage = "empty" | "connected" | "syncing" | "failed" | "ready";

export type FirstSteps = {
  stage: Stage;
  /** Connected sources that fail, each with what the API knows of why. */
  failing: Source[];
  /** What is read, by category, in the catalogue's order. */
  read: ConnectorCategory[];
};

const isRead = (source: Source) =>
  isConnected(source) &&
  source.last_sync_at !== null &&
  source.sync_status !== "running";

const isFailing = (source: Source) =>
  isConnected(source) &&
  (source.sync_status === "failed" || source.status === "error");

export function firstStepsOf(all: readonly Source[]): FirstSteps {
  const connected = all.filter(isConnected);
  const failing = connected.filter(isFailing);
  const read = new Set(
    connected.filter(isRead).map((s) => KIND_CATEGORY[s.type]),
  );
  let stage: Stage = "empty";
  if (read.size > 0) stage = "ready";
  else if (connected.some((s) => s.sync_status === "running"))
    stage = "syncing";
  else if (failing.length > 0) stage = "failed";
  else if (connected.length > 0) stage = "connected";
  return {
    stage,
    failing,
    read: CATEGORY_ORDER.filter((c): c is ConnectorCategory =>
      read.has(c as ConnectorCategory),
    ),
  };
}

const HIDDEN_KEY = "leka.first-steps.hidden";

export function FirstStepsCard({ sources }: { sources: readonly Source[] }) {
  const t = useDictionary();
  const w = t.overview.firstSteps;
  const counts = useIntentionCounts();
  const inDemo = useInDemo();
  // A customer's own organisation (2026-10-25): its data only, no demonstration.
  const enterprise = useEnterprise();
  const [hidden, setHidden] = useState(true);

  // Read after mount: the server has no localStorage.
  useEffect(() => {
    try {
      setHidden(window.localStorage.getItem(HIDDEN_KEY) === "1");
    } catch {
      setHidden(false);
    }
  }, []);

  const steps = firstStepsOf(sources);
  const asked = (counts.data?.all ?? 0) > 0;
  if (hidden || !counts.data || (steps.stage === "ready" && asked)) return null;

  function hide() {
    setHidden(true);
    try {
      window.localStorage.setItem(HIDDEN_KEY, "1");
    } catch {
      // Not remembered: it comes back on the next visit, nothing lost.
    }
  }

  const showDemo = steps.stage !== "ready" && !inDemo && !enterprise;
  // Nothing connected (2026-10-25): Confluence first — the documentation
  // LEKA reads best —, any other tool beside it.
  const action =
    steps.stage === "empty"
      ? { label: w.connectConfluence, href: `${routes.sources()}?connect=confluence` }
      : steps.stage === "failed" && steps.failing[0]
        ? { label: w.fix, href: routes.source(steps.failing[0].id) }
        : steps.stage !== "ready"
          ? { label: w.seeSources, href: routes.sources() }
          : null;

  const done = (steps.stage === "ready" ? 1 : 0) + (asked ? 1 : 0);
  return (
    // A strip under the history (2026-10-25: « le gros carré prend toute la
    // place »): where one stands, what to do now, one line each.
    <section
      className="mt-3 rounded-2xl border border-shell-line bg-white p-3 shadow-[0_1px_2px_rgba(16,24,40,0.04)]"
      aria-labelledby="first-steps-title"
      data-testid="first-steps"
      data-stage={steps.stage}
    >
      <div className="flex items-start gap-3">
        <Progress done={done} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <h2 id="first-steps-title" className="text-sm font-semibold text-brand-navy">
              {w.title}
            </h2>
            <ol className="flex flex-wrap items-center gap-1.5">
              <StepChip done={steps.stage === "ready"} label={w.step1} />
              <StepChip done={asked} label={w.step2} />
            </ol>
          </div>
          <p
            className="mt-1 text-[0.8125rem] text-shell-muted"
            data-testid="first-steps-stage"
          >
            {steps.stage === "ready"
              ? fill(w.stages.ready, {
                  parts: steps.read
                    .map((c) => t.sources.categories[c].toLowerCase())
                    .join(", "),
                })
              : w.stages[steps.stage]}
          </p>
          {steps.failing.length > 0 ? (
            <ul className="mt-1 space-y-1" data-testid="first-steps-failing">
              {steps.failing.slice(0, 2).map((source) => (
                <li key={source.id} className="flex gap-1.5 text-xs">
                  <TriangleAlert
                    className="mt-px size-3.5 shrink-0 text-state-warning"
                    aria-hidden="true"
                  />
                  <span className="min-w-0">
                    <Link
                      href={routes.source(source.id)}
                      className="font-medium text-brand-navy underline-offset-2 hover:underline"
                    >
                      {source.display_name}
                    </Link>{" "}
                    <span className="text-shell-muted">
                      {source.last_error
                        ? `${source.last_error.message} ${source.last_error.remediation}`
                        : w.failedUnknown}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          <p className="mt-0.5 text-xs text-shell-muted" data-testid="first-steps-ask">
            {steps.stage === "ready" ? w.ask : w.askFirst}
          </p>
          {action || steps.stage === "empty" || showDemo ? (
            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              {action ? (
                <Link
                  href={action.href}
                  className={buttonVariants({ size: "sm" })}
                  data-testid="first-steps-action"
                >
                  {action.label}
                </Link>
              ) : null}
              {steps.stage === "empty" ? (
                <Link
                  href={routes.welcome()}
                  className={buttonVariants({ size: "sm", variant: "outline" })}
                  data-testid="first-steps-other"
                >
                  {w.otherSource}
                </Link>
              ) : null}
              {/* Nothing read yet: Nova Retail, the demonstration, to see it first (LEKA-451). */}
              {showDemo ? (
                <span data-testid="first-steps-demo" title={t.demo.exploreHint}>
                  <ExploreDemoButton variant="outline" />
                </span>
              ) : null}
            </div>
          ) : null}
        </div>
        <button
          type="button"
          onClick={hide}
          aria-label={w.hide}
          title={w.hide}
          className="rounded p-1 text-shell-muted outline-none hover:text-brand-navy focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </div>
    </section>
  );
}

/** Where one stands: two steps, a ring filled by what is done. */
function Progress({ done }: { done: number }) {
  return (
    <span className="relative flex size-9 shrink-0 items-center justify-center" aria-hidden="true">
      <svg viewBox="0 0 36 36" className="absolute inset-0 size-full -rotate-90">
        <circle cx="18" cy="18" r="15" fill="none" strokeWidth="3" className="stroke-brand-violet-soft" />
        <circle
          cx="18"
          cy="18"
          r="15"
          fill="none"
          strokeWidth="3"
          strokeLinecap="round"
          className="stroke-shell-nav-active"
          strokeDasharray={`${(done / 2) * 94.25} 94.25`}
        />
      </svg>
      <span className="text-[0.6875rem] font-semibold tabular-nums text-brand-navy">{done}/2</span>
    </span>
  );
}

function StepChip({ done, label }: { done: boolean; label: string }) {
  const t = useDictionary();
  return (
    <li
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        done ? "bg-state-success-soft text-state-success" : "bg-shell-canvas text-shell-muted",
      )}
    >
      {done ? (
        <CircleCheck className="size-3.5" aria-hidden="true" />
      ) : (
        <span className="size-2.5 rounded-full border-[1.5px] border-current" aria-hidden="true" />
      )}
      {label}
      {done ? <span className="sr-only">{t.overview.firstSteps.done}</span> : null}
    </li>
  );
}