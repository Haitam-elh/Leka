"use client";

import { ArrowRight, CirclePause, Clock, RotateCw } from "lucide-react";
import Link from "next/link";

import { Pill } from "@/components/intelligence/pill";
import { useConfirm } from "@/components/interactions/confirm";
import { timeAgo } from "@/components/knowledge/time";
import { useCurrentUser, usePermissions } from "@/components/shell/shell-provider";
import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { Intention, IntentionDetail } from "@/lib/intentions/api";
import {
  JOURNEY_TONES,
  type Journey,
  type JourneyControl,
  journeyLate,
  journeyNext,
  journeyTechnical,
  journeyWhy,
  may,
} from "@/lib/intentions/journey";
import { useAnalyseAgain, useIntentionChange } from "@/lib/intentions/queries";
import { notify } from "@/lib/notify";

/**
 * An intention's journey, drawn (LEKA-443). Every screen draws it the same
 * way: the list, its panel, its page, the overview.
 *
 *     JourneyPill   its state, in its words and tone
 *     JourneyNote   on its page:
 *                   - what happened, and since when;
 *                   - what comes next and who;
 *                   - the controls its state allows, to whoever may use
 *                     them;
 *                   - a technical error, folded, for whoever diagnoses it
 *
 * The state, its reason, its controls are the API's. Nothing here decides
 * them.
 */

export function JourneyPill({ journey, status }: { journey: Journey; status?: string }) {
  const t = useDictionary();
  return (
    <Pill
      tone={JOURNEY_TONES[journey.state]}
      dot
      data-testid="intention-status"
      data-status={status}
      data-state={journey.state}
    >
      {t.intentions.journey.states[journey.state]}
    </Pill>
  );
}

/** Whether this person is its asker, and whether they may approve. */
export function useRights(intention: Pick<Intention, "created_by">) {
  const me = useCurrentUser();
  const steward = usePermissions()?.includes("intention:approve") ?? false;
  const yours = Boolean(me?.id) && intention.created_by === me?.id;
  return { yours, steward };
}

/** « Arrêter l'analyse » (mockup 03): confirmed; its partial results kept. */
export function StopAnalysis({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.intentions.journey;
  const confirm = useConfirm();
  const change = useIntentionChange(intention.id);
  const rights = useRights(intention);
  if (!may(intention.journey, "stop", rights)) return null;
  return (
    <Button
      type="button"
      variant="outline"
      disabled={change.isPending}
      data-testid="intention-stop"
      onClick={async () => {
        const yes = await confirm({
          title: w.stopTitle,
          description: w.stopBody,
          confirmLabel: w.stopConfirm,
        });
        if (!yes) return;
        try {
          await change.mutateAsync({ change: "stop" });
          notify.success({ title: w.stopped });
        } catch (error) {
          notify.error({ title: error instanceof ApiError ? error.message : String(error) });
        }
      }}
    >
      <CirclePause className="size-4" aria-hidden="true" />
      {w.controls.stop}
    </Button>
  );
}

/** Resumed, or analysed again — the same route, its state says which. */
function AnalyseButton({
  intention,
  control,
}: {
  intention: IntentionDetail;
  control: "resume" | "analyse_again";
}) {
  const t = useDictionary();
  const w = t.intentions.journey;
  const again = useAnalyseAgain(intention.id);
  return (
    <Button
      type="button"
      size="sm"
      disabled={again.isPending}
      data-testid={`journey-${control}`}
      onClick={async () => {
        try {
          const { queued } = await again.mutateAsync();
          notify.success({ title: queued ? w.resumed : t.intentions.analysis.already });
        } catch (error) {
          notify.error({ title: error instanceof ApiError ? error.message : String(error) });
        }
      }}
    >
      <RotateCw className="size-4" aria-hidden="true" />
      {w.controls[control]}
    </Button>
  );
}

type ControlLabel = keyof Dictionary["intentions"]["journey"]["controls"];

/** Where its next step is taken, by next step: the address, the control it
 * needs — none, anyone who reads it — and its words. */
const NEXT_STEP: Record<
  string,
  { control: JourneyControl | null; label: ControlLabel; href: (id: string) => string }
> = {
  // Its questions, where they are answered — never the page it is on
  // (2026-10-24: « Répondre » did nothing).
  answer: {
    control: "answer",
    label: "answer",
    href: (id) => `${routes.intention(id, "overview")}#brief-questions`,
  },
  // Nothing to answer, only its context in the way: its request made
  // precise, asked again (LEKA-385).
  clarify: {
    control: "ask_again",
    label: "clarify",
    href: (id) => `${routes.intentionNew()}?intention=${id}`,
  },
  decide: { control: "decide", label: "decide", href: (id) => routes.intention(id, "decision") },
  start_actions: {
    control: "start_actions",
    label: "start_actions",
    href: (id) => routes.intention(id, "actions"),
  },
  retry_actions: {
    control: "retry_actions",
    label: "retry_actions",
    href: (id) => routes.intention(id, "actions"),
  },
  wait_verification: {
    control: "report_outcome",
    label: "report_outcome",
    href: (id) => routes.intention(id, "actions"),
  },
  read_result: { control: null, label: "read_result", href: (id) => routes.intention(id, "results") },
  follow_actions: {
    control: null,
    label: "follow_actions",
    href: (id) => routes.intention(id, "actions"),
  },
};

/** The control its next step asks for, when this person may use it. */
function NextControl({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const journey = intention.journey;
  const rights = useRights(intention);
  if (may(journey, "resume", rights)) return <AnalyseButton intention={intention} control="resume" />;
  if ((journey.next === "analyse_again" || journey.late) && may(journey, "analyse_again", rights)) {
    return <AnalyseButton intention={intention} control="analyse_again" />;
  }
  const step = NEXT_STEP[journey.next];
  if (!step || (step.control && !may(journey, step.control, rights))) return null;
  return (
    <Link
      href={step.href(intention.id)}
      className={buttonVariants({ size: "sm" })}
      data-testid="journey-next"
    >
      {t.intentions.journey.controls[step.label]}
      <ArrowRight className="rtl:-scale-x-100 size-4" aria-hidden="true" />
    </Link>
  );
}

/** What happened, since when, what comes next and who — on its page. */
export function JourneyNote({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.intentions.journey;
  const journey = intention.journey;
  const ago = timeAgo(t, journey.since);
  const since = fill(w.since, { ago: ago.charAt(0).toLocaleLowerCase(locale) + ago.slice(1) });
  const why = journeyWhy(t, journey);
  const next = journeyNext(t, journey);
  const late = journeyLate(t, journey);
  const technical = journeyTechnical(t, journey, intention.version);
  return (
    <section
      aria-label={w.label}
      className="mb-4 flex flex-col gap-2 rounded-xl border border-shell-line bg-white px-5 py-4"
      data-testid="journey-note"
      data-state={journey.state}
      data-reason={journey.reason ?? undefined}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {/* Its state is the banner's pill, just above: said once. */}
        <span className="text-[0.8125rem] text-shell-muted" data-testid="journey-since">
          {since}
        </span>
        {intention.version > 1 ? (
          <Pill tone="neutral" data-testid="intention-version">
            {fill(w.version, { version: intention.version })}
          </Pill>
        ) : null}
      </div>
      {why ? (
        <p className="text-[0.875rem] text-brand-navy" data-testid="journey-why">
          {why}
        </p>
      ) : null}
      {late ? (
        <p
          className="flex items-center gap-1.5 text-[0.8125rem] text-state-warning"
          data-testid="journey-late"
        >
          <Clock className="size-4 shrink-0" aria-hidden="true" />
          {late}
        </p>
      ) : null}
      {next ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-[0.8125rem] text-shell-muted" data-testid="journey-next-said">
            <span className="font-medium text-brand-navy">
              {journey.by ? w.by[journey.by] : w.next_label}
            </span>
            {" · "}
            {next}
          </p>
          <NextControl intention={intention} />
        </div>
      ) : null}
      {technical ? (
        <details className="text-xs text-shell-muted" data-testid="journey-technical">
          <summary className="cursor-pointer">{w.technical}</summary>
          <p className="mt-1 font-mono">{technical}</p>
        </details>
      ) : null}
    </section>
  );
}
