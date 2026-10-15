"use client";

import { CircleCheck, Compass, TriangleAlert, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { cn } from "cn";
import { ExploreDemoButton } from "@/components/demo/demo";
import { useInDemo } from "@/components/demo/in-demo";
import { buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
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
 * The examples follow what is read: a code source, questions on code. Until
 * something is read they are said to be examples — LEKA cannot answer them
 * yet — never shown as the workspace's own.
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

/** The examples, by what is read; the general ones until something is. */
const EXAMPLE_CATEGORIES = [
  "code",
  "project",
  "docs",
  "cloud",
  "observability",
  "data",
] as const;
type ExampleCategory = (typeof EXAMPLE_CATEGORIES)[number];

export function examplesOf(
  read: readonly ConnectorCategory[],
): ExampleCategory[] | null {
  const mine = EXAMPLE_CATEGORIES.filter((c) => read.includes(c));
  return mine.length > 0 ? mine.slice(0, 3) : null;
}

const HIDDEN_KEY = "leka.first-steps.hidden";

export function FirstStepsCard({ sources }: { sources: readonly Source[] }) {
  const t = useDictionary();
  const w = t.overview.firstSteps;
  const counts = useIntentionCounts();
  const inDemo = useInDemo();
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

  const mine = examplesOf(steps.read);
  const examples = (mine ?? ["code", "project", "observability"]).map(
    (c) => w.examples[c],
  );
  const action =
    steps.stage === "empty"
      ? { label: w.connect, href: routes.welcome() }
      : steps.stage === "failed" && steps.failing[0]
        ? { label: w.fix, href: routes.source(steps.failing[0].id) }
        : steps.stage !== "ready"
          ? { label: w.seeSources, href: routes.sources() }
          : null;

  return (
    <section
      className="mt-4 rounded-xl border border-brand-violet/30 bg-brand-violet-soft/40 p-4"
      aria-labelledby="first-steps-title"
      data-testid="first-steps"
      data-stage={steps.stage}
    >
      <div className="flex items-start gap-3">
        <Compass
          className="mt-0.5 size-5 shrink-0 text-shell-nav-active"
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1">
          <h2
            id="first-steps-title"
            className="text-[1.0625rem] font-semibold text-brand-navy"
          >
            {w.title}
          </h2>
          <p className="mt-1 text-sm text-shell-muted">{w.value}</p>
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

      <ol className="mt-4 grid gap-3 md:grid-cols-2">
        <li className="rounded-lg border border-shell-line bg-white p-3">
          <StepHead done={steps.stage === "ready"} label={w.step1} />
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
            <ul className="mt-2 space-y-1.5" data-testid="first-steps-failing">
              {steps.failing.slice(0, 3).map((source) => (
                <li key={source.id} className="flex gap-2 text-[0.8125rem]">
                  <TriangleAlert
                    className="mt-0.5 size-4 shrink-0 text-state-warning"
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
          {action ? (
            <Link
              href={action.href}
              className={cn(buttonVariants({ size: "sm" }), "mt-3")}
              data-testid="first-steps-action"
            >
              {action.label}
            </Link>
          ) : null}
          {/* Nothing read yet: Nova Retail, the demonstration, to see it first (LEKA-451). */}
          {steps.stage !== "ready" && !inDemo ? (
            <div className="mt-3 border-t border-shell-line pt-3" data-testid="first-steps-demo">
              <p className="mb-2 text-[0.8125rem] text-shell-muted">{t.demo.exploreHint}</p>
              <ExploreDemoButton />
            </div>
          ) : null}
        </li>
        <li className="rounded-lg border border-shell-line bg-white p-3">
          <StepHead done={asked} label={w.step2} />
          <p className="mt-1 text-[0.8125rem] text-shell-muted">
            {mine ? w.examplesMine : w.examplesOnly}
          </p>
          <ul
            className="mt-2 flex flex-col gap-1.5"
            data-testid="first-steps-examples"
          >
            {examples.map((words) => (
              <li key={words}>
                <Link
                  href={`${routes.intentionNew()}?q=${encodeURIComponent(words)}`}
                  className="block rounded-md border border-shell-line px-2.5 py-1.5 text-[0.8125rem] text-brand-navy outline-none hover:border-brand-violet focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                >
                  {words}
                </Link>
              </li>
            ))}
          </ul>
        </li>
      </ol>
    </section>
  );
}

function StepHead({ done, label }: { done: boolean; label: string }) {
  const t = useDictionary();
  return (
    <p className="flex items-center gap-2 text-sm font-medium text-brand-navy">
      {done ? (
        <CircleCheck className="size-4 text-state-success" aria-hidden="true" />
      ) : (
        <span
          className="size-4 rounded-full border-2 border-shell-line"
          aria-hidden="true"
        />
      )}
      {label}
      {done ? (
        <span className="sr-only">{t.overview.firstSteps.done}</span>
      ) : null}
    </p>
  );
}
