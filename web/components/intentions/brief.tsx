"use client";

import { CircleCheck, CircleHelp, Lock, MessageCircleQuestion, Undo2 } from "lucide-react";
import { useState } from "react";

import { cn } from "cn";

import { Card } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { exactDate } from "@/components/knowledge/time";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { modelTitle } from "@/lib/models";
import type {
  BriefQuestion,
  BriefSlot,
  IntentionAnswer,
  IntentionBrief,
  IntentionDetail,
} from "@/lib/intentions/api";

/**
 * An intention's brief (LEKA-439): what LEKA understood — its goal, what
 * it is about, where and when, what is expected back, what must hold —
 * each said as known, assumed by LEKA (never shown as a fact), missing or
 * not known; then what LEKA still needs, the blocking first, each question
 * with why it is asked and what it could be — the things it may mean, the
 * environments it knows, their own words, « je ne sais pas »; and what
 * follows: analyse, clarify, go on with its limits said, or block.
 *
 * The same before an intention is asked (the composer) and after (its
 * page): `onAnswer` is how an answer is given — read again before it is
 * asked, sent to the API after.
 */

type Understanding = NonNullable<IntentionDetail["understanding"]>;

const STATE_TONES = {
  known: "success",
  assumed: "info",
  missing: "warning",
  unknown: "neutral",
} as const;

export function BriefView({
  brief,
  understanding,
  answers = [],
  onAnswer,
  pending = false,
}: {
  brief: IntentionBrief;
  understanding: Understanding;
  /** What its asker answered, kept: said, so it can be checked. */
  answers?: readonly IntentionAnswer[];
  onAnswer?: (answer: IntentionAnswer) => void;
  pending?: boolean;
}) {
  const t = useDictionary();
  const w = t.intentions.brief;
  const u = t.intentions.understanding;
  const blocking = brief.questions.filter((q) => q.blocking);
  const optional = brief.questions.filter((q) => !q.blocking && askable(q));
  const asked = new Set(brief.questions.map((q) => q.kind));
  // Answered and settled: no longer asked, still said.
  const settled = answers.filter((a) => !asked.has(a.question));
  // An answer by id is the thing it named; a code, its words.
  const things = [...(understanding.scope?.entities ?? []), ...understanding.entities];
  const nameOf = (value: string) =>
    things.find((thing) => thing.entity_id === value)?.name ??
    (w.choices as Record<string, string>)[value] ??
    (u.goals as Record<string, string>)[value] ??
    (u.actionNames as Record<string, string>)[value] ??
    value;
  const readBy =
    understanding.read_by?.method === "model" && understanding.read_by.model
      ? fill(u.readBy, { model: modelTitle(understanding.read_by.model) })
      : null;
  return (
    <div className="flex flex-col gap-4" data-testid="intention-brief" data-decision={brief.decision}>
      <Card title={w.title}>
        {brief.restated || readBy ? (
          <div className="mb-3" data-testid="brief-restated">
            {brief.restated ? (
              <p className="text-[0.9375rem] text-brand-navy" dir="auto">
                {brief.restated}
              </p>
            ) : null}
            {readBy ? <p className="text-xs text-shell-muted">{readBy}</p> : null}
          </div>
        ) : null}
        <dl className="grid gap-x-4 gap-y-2.5 text-[0.8125rem] sm:grid-cols-[minmax(0,9rem)_minmax(0,1fr)_auto]">
          {brief.slots.map((slot) => (
            <SlotRow key={slot.slot} slot={slot} understanding={understanding} />
          ))}
        </dl>
        {settled.length ? (
          <div className="mt-3 border-t border-shell-line pt-3" data-testid="brief-answers">
            <p className="mb-1 text-xs font-semibold text-shell-muted">{w.yours}</p>
            <ul className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
              {settled.map((a) => (
                <li key={a.question} dir="auto">
                  {(u.questions as Record<string, string>)[a.question] ?? a.question}{" "}
                  <span className="font-medium">
                    {a.unknown ? w.answeredUnknown : nameOf(a.value ?? "")}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </Card>

      {blocking.length ? (
        <section
          aria-labelledby="brief-questions"
          className="rounded-xl border border-state-warning/40 bg-white p-4"
          data-testid="brief-questions"
        >
          <h2 id="brief-questions" className="mb-3 flex items-center gap-2 text-[1rem] font-semibold text-brand-navy">
            <MessageCircleQuestion className="size-4 text-state-warning" aria-hidden="true" />
            {w.questions}
          </h2>
          <ul className="flex flex-col gap-4">
            {blocking.map((question) => (
              <QuestionItem
                key={question.kind}
                question={question}
                onAnswer={onAnswer}
                pending={pending}
              />
            ))}
          </ul>
        </section>
      ) : null}

      {optional.length ? (
        <details className="rounded-xl border border-shell-line bg-white p-4" data-testid="brief-optional">
          <summary className="cursor-pointer text-[0.875rem] font-semibold text-brand-navy">
            {w.optional}
          </summary>
          <ul className="mt-3 flex flex-col gap-4">
            {optional.map((question) => (
              <QuestionItem
                key={question.kind}
                question={question}
                onAnswer={onAnswer}
                pending={pending}
              />
            ))}
          </ul>
        </details>
      ) : null}

      <Decision brief={brief} />
    </div>
  );
}

/** Whether a question can be answered here: a choice, an option, words. */
function askable(question: BriefQuestion): boolean {
  return question.free || question.choices.length > 0 || optionsOf(question).length > 0;
}

/** What it could be, as values an answer gives back. */
function optionsOf(question: BriefQuestion): string[] {
  switch (question.kind) {
    case "ambiguous_action":
      return ["yes", "no"];
    case "conflicting_constraints":
      return question.options;
    case "unclear_goal":
    case "competing_goals":
    case "unknown_environment":
    case "missing_environment":
      return question.options;
    default:
      // Names without ids (things it may mean): their words.
      return question.choices.length ? [] : question.options;
  }
}

function SlotRow({ slot, understanding }: { slot: BriefSlot; understanding: Understanding }) {
  const t = useDictionary();
  const w = t.intentions.brief;
  const u = t.intentions.understanding;
  const { format: locale } = useLocale();
  const values = slot.values ?? [];
  let value: string;
  switch (slot.slot) {
    case "goal":
      value = (u.goals as Record<string, string>)[slot.value ?? "unknown"] ?? slot.value ?? "—";
      break;
    case "target":
      value = values.length
        ? values.join(", ")
        : slot.need === "blocking"
          ? w.nothingSaid
          : w.everything;
      break;
    case "scope": {
      const where = values.length ? values.join(", ") : u.scope.everywhere;
      const period = understanding.scope?.period;
      const when = period
        ? `${exactDate(locale, period.since)} → ${exactDate(locale, period.until)}`
        : w.noPeriod;
      value = `${where} · ${when}`;
      break;
    }
    case "expected": {
      value = (w.expected as Record<string, string>)[slot.value ?? "answer"] ?? slot.value ?? "—";
      const acts = understanding.actions.filter((a) => a.changes_systems);
      if (slot.value === "action" && acts.length) {
        const names = u.actionNames as Record<string, string>;
        value = fill(w.expectedAction, {
          expected: value,
          actions: acts.map((a) => names[a.code] ?? a.code).join(", "),
        });
      }
      break;
    }
    default:
      value = values.length
        ? values.map((k) => (u.scope.kinds as Record<string, string>)[k] ?? k).join(", ")
        : w.nothingSaid;
  }
  return (
    <div className="contents" data-testid="brief-slot" data-slot={slot.slot} data-state={slot.state}>
      <dt className="text-shell-muted">{w.slots[slot.slot]}</dt>
      <dd className="min-w-0 font-medium text-brand-navy" dir="auto">
        {value}
      </dd>
      <dd>
        <Pill tone={STATE_TONES[slot.state]}>{w.states[slot.state]}</Pill>
      </dd>
    </div>
  );
}

function QuestionItem({
  question,
  onAnswer,
  pending,
}: {
  question: BriefQuestion;
  onAnswer?: (answer: IntentionAnswer) => void;
  pending: boolean;
}) {
  const t = useDictionary();
  const w = t.intentions.brief;
  const u = t.intentions.understanding;
  const [words, setWords] = useState("");
  const [changing, setChanging] = useState(false);
  const answer = question.answer;
  const asked = (u.questions as Record<string, string>)[question.kind] ?? question.said;
  const why = (w.whys as Record<string, string>)[question.kind];

  function give(value: string | null, unknown = false) {
    onAnswer?.({ question: question.kind, value, unknown });
    setChanging(false);
    setWords("");
  }

  function said(value: string): string {
    const choice = question.choices.find((c) => c.value === value);
    if (choice) return choice.label;
    return (
      (w.choices as Record<string, string>)[value] ??
      (u.goals as Record<string, string>)[value] ??
      (u.actionNames as Record<string, string>)[value] ??
      value
    );
  }

  const settled = answer && !changing;
  return (
    <li className="flex flex-col gap-2" data-testid="brief-question" data-kind={question.kind}>
      <p className="flex items-start gap-2 text-[0.875rem] font-semibold text-brand-navy">
        {question.blocking ? (
          <Lock className="mt-0.5 size-3.5 shrink-0 text-state-warning" aria-hidden="true" />
        ) : (
          <CircleHelp className="mt-0.5 size-3.5 shrink-0 text-shell-muted" aria-hidden="true" />
        )}
        {asked}
      </p>
      {why ? (
        <p className="text-[0.8125rem] text-shell-muted" data-testid="brief-why">
          <span className="font-medium">{w.why}</span> {why}
        </p>
      ) : null}
      {settled ? (
        <p className="flex flex-wrap items-center gap-2 text-[0.8125rem] text-brand-navy" data-testid="brief-answer">
          <CircleCheck className="size-4 text-state-success" aria-hidden="true" />
          {answer.unknown ? w.answeredUnknown : fill(w.answered, { answer: said(answer.value ?? "") })}
          {onAnswer ? (
            <button
              type="button"
              onClick={() => setChanging(true)}
              className="inline-flex items-center gap-1 rounded text-brand-violet hover:underline"
            >
              <Undo2 className="size-3.5" aria-hidden="true" />
              {w.change}
            </button>
          ) : null}
        </p>
      ) : onAnswer ? (
        <div className="flex flex-col gap-2">
          {question.choices.length || optionsOf(question).length ? (
            <div className="flex flex-wrap gap-2" role="group" aria-label={asked}>
              {question.choices.map((choice) => (
                <Button
                  key={choice.value}
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={pending}
                  onClick={() => give(choice.value)}
                  data-testid="brief-choice"
                >
                  {choice.label}
                </Button>
              ))}
              {optionsOf(question).map((option) => (
                <Button
                  key={option}
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={pending}
                  onClick={() => give(option)}
                  data-testid="brief-option"
                >
                  {said(option)}
                </Button>
              ))}
            </div>
          ) : null}
          {question.free ? (
            // Never a form of its own: it sits inside the composer's, and a
            // nested form would send that one too.
            <div className="flex flex-wrap items-center gap-2">
              <Input
                value={words}
                onChange={(event) => setWords(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter") return;
                  event.preventDefault();
                  if (words.trim()) give(words.trim());
                }}
                placeholder={w.yourWords}
                aria-label={w.yourWords}
                maxLength={300}
                className="h-9 min-w-0 flex-1"
                data-testid="brief-words"
              />
              <Button
                type="button"
                size="sm"
                disabled={pending || !words.trim()}
                onClick={() => give(words.trim())}
                data-testid="brief-send"
              >
                {w.send}
              </Button>
            </div>
          ) : null}
          <div>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={pending}
              onClick={() => give(null, true)}
              data-testid="brief-unknown"
            >
              {w.unknown}
            </Button>
          </div>
        </div>
      ) : null}
    </li>
  );
}

function Decision({ brief }: { brief: IntentionBrief }) {
  const t = useDictionary();
  const w = t.intentions.brief;
  const limits = brief.limits
    .map((kind) => (w.limits as Record<string, string>)[kind] ?? kind)
    .join(", ");
  const said =
    brief.decision === "continue"
      ? fill(w.decisions.continue, { limits })
      : w.decisions[brief.decision];
  return (
    <p
      role="status"
      className={cn(
        "rounded-lg px-4 py-3 text-[0.8125rem]",
        brief.decision === "analyse" && "bg-state-success-soft text-brand-navy",
        brief.decision === "continue" && "bg-state-info-soft text-brand-navy",
        brief.decision === "clarify" && "bg-state-warning-soft text-brand-navy",
        brief.decision === "block" && "bg-state-danger-soft text-brand-navy",
      )}
      data-testid="brief-decision"
    >
      {said}
    </p>
  );
}
