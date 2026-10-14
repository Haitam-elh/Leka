"use client";

import { Check } from "lucide-react";
import Link from "next/link";

import { useDictionary } from "@/lib/i18n/locale-provider";
import type { IntentionStatus } from "@/lib/intentions/api";

/**
 * The five steps of an intention, as mockups 02 to 06 draw them across the
 * top of the page: Votre intention, Analyse, Résultats, Décision, Action —
 * each with its line underneath. A step done is a check on a pale disc; the
 * one it is at, a filled violet disc; one to come, its number in grey. The
 * line between two steps is violet as far as it got.
 *
 * Where an intention stands is its status's to say (stepOf). A step reached
 * opens its view when given an address (`href`); one to come does not.
 */

export const STEPS = [
  "intention",
  "analysis",
  "results",
  "decision",
  "action",
] as const;
export type Step = (typeof STEPS)[number];

/** Where an intention stands: the step it is at, and the last one it can
 * reach. A question answered ends at its results: deciding and acting are
 * not needed. */
export function stepOf(
  status: IntentionStatus,
  decides = true,
): { at: Step; reached: number } {
  switch (status) {
    case "needs_clarification":
      return { at: "intention", reached: 0 };
    case "submitted":
    case "analysing":
      return { at: "analysis", reached: 1 };
    case "awaiting_decision":
      return { at: "decision", reached: 3 };
    case "approved":
    case "scheduled":
    case "executing":
    case "verifying":
      return { at: "action", reached: 4 };
    case "rejected":
      return { at: "decision", reached: 3 };
    case "completed":
      return decides
        ? { at: "action", reached: 4 }
        : { at: "results", reached: 2 };
    default:
      // failed, cancelled: where they stopped is said by the page.
      return { at: "analysis", reached: 1 };
  }
}

export function IntentionStepper({
  current,
  shown,
  reached,
  done,
  hrefOf,
  testIdOf,
  last,
}: {
  /** Where the intention is. */
  current: Step;
  /** The step whose view is open. */
  shown?: Step;
  /** The last step it can open (index). */
  reached: number;
  /** Whether the current step is itself finished (a question answered). */
  done?: boolean;
  hrefOf?: (step: Step) => string;
  /** Each step's link, named for the tests and the tour. */
  testIdOf?: (step: Step) => string;
  /** The last step it goes through (index): a question answered needs no
   * decision nor action — those are said not needed. */
  last?: number;
}) {
  const t = useDictionary().intentions.steps;
  const at = STEPS.indexOf(current);
  return (
    <nav
      aria-label={t.label}
      className="-mx-2 mb-4 overflow-x-auto"
      data-testid="intention-stepper"
    >
      {/* Room inside the scroller for a disc's ring and halo (6px): a
          scroller clips what overflows it, the top of the open step's ring
          with it (2026-10-14). */}
      <ol className="flex min-w-[42rem] items-start px-2 py-2">
        {STEPS.map((step, i) => {
          const skipped = last !== undefined && i > last;
          const finished = !skipped && (i < at || (i === at && done));
          const here = !skipped && i === at && !done;
          const open = shown === step;
          const reachable = !skipped && i <= reached && hrefOf !== undefined;
          const disc = (
            <span
              className={[
                "relative z-10 flex size-9 items-center justify-center rounded-full text-[0.875rem] font-semibold transition-colors",
                here
                  ? "bg-brand-violet text-white shadow-[0_0_0_6px_var(--brand-violet-soft)]"
                  : finished
                    ? "bg-brand-violet-soft text-brand-violet"
                    : skipped
                      ? "border border-dashed border-shell-line bg-shell-canvas text-shell-muted"
                      : "border border-shell-line bg-white text-shell-muted",
                open && !here ? "ring-2 ring-brand-violet" : "",
              ].join(" ")}
              aria-hidden="true"
            >
              {finished ? <Check className="size-4" /> : skipped ? "–" : i + 1}
            </span>
          );
          const label = (
            <span className="mt-2 flex flex-col items-center text-center">
              <span
                // The step on screen reads as an open tab — violet, underlined —
                // apart from where the intention stands, the filled disc
                // (LEKA-438: on Analyse, the disc at Décision read as "here").
                className={`text-[0.875rem] font-semibold ${open ? "text-brand-violet underline decoration-2 underline-offset-[6px]" : here || finished ? "text-brand-navy" : "text-shell-muted"}`}
              >
                {t[step].title}
              </span>
              <span className="text-[0.75rem] text-shell-muted">
                {skipped ? t.skipped : t[step].hint}
              </span>
            </span>
          );
          return (
            <li
              key={step}
              className="relative flex flex-1 flex-col items-center"
              data-testid={`intention-step-${step}`}
              data-state={
                finished
                  ? "done"
                  : here
                    ? "current"
                    : skipped
                      ? "skipped"
                      : "todo"
              }
              aria-current={here ? "step" : undefined}
            >
              {/* The line to the next step: violet as far as it got. */}
              {i < STEPS.length - 1 ? (
                <span
                  className={`absolute top-[1.125rem] start-1/2 h-0.5 w-full ${i < at ? "bg-brand-violet" : "bg-shell-line"}`}
                  aria-hidden="true"
                />
              ) : null}
              {reachable ? (
                <Link
                  href={hrefOf(step)}
                  data-testid={testIdOf?.(step)}
                  aria-current={open ? "page" : undefined}
                  className="flex flex-col items-center rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                  aria-label={`${i + 1}. ${t[step].title}`}
                >
                  {disc}
                  {label}
                </Link>
              ) : (
                <span className="flex flex-col items-center">
                  {disc}
                  {label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** « Étape 2 sur 5 », as each mockup says it top right. */
export function StepBadge({ step }: { step: Step }) {
  const t = useDictionary().intentions.steps;
  return (
    <span
      className="inline-flex h-10 items-center rounded-lg bg-shell-canvas px-4 text-[0.875rem] text-shell-muted"
      data-testid="intention-step-badge"
    >
      {t.of
        .replace("{n}", String(STEPS.indexOf(step) + 1))
        .replace("{total}", String(STEPS.length))}
    </span>
  );
}
