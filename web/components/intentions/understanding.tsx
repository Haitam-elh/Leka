"use client";

import { AlertTriangle, Brain, Info, PencilLine } from "lucide-react";
import Link from "next/link";

import { Card, entityHref } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { IntentionDetail } from "@/lib/intentions/api";

/**
 * What LEKA understood of an intention (LEKA-385): a question or a request,
 * its goal, the actions asked — those that would change a customer's
 * systems said so — what it is about, each with the words it came from;
 * and, when LEKA cannot go on, what it asks, with what it could mean.
 * Every word here is the API's understanding (`intention.understanding`),
 * said again in the reader's language.
 */

export type UnderstandingRead = NonNullable<IntentionDetail["understanding"]>;

export function UnderstandingPanel({
  understanding,
  intentionId,
}: {
  understanding: UnderstandingRead;
  /** Given, a request not understood enough leads to clarifying it. */
  intentionId?: string;
}) {
  const t = useDictionary();
  const w = t.intentions.understanding;
  const goals = w.goals as Record<string, string>;
  const actions = w.actionNames as Record<string, string>;
  const questions = w.questions as Record<string, string>;
  const blocking = understanding.ambiguities.filter((a) => a.blocking);
  const notes = understanding.ambiguities.filter((a) => !a.blocking);

  return (
    <Card title={w.title} icon={<Brain className="size-4 text-shell-muted" aria-hidden="true" />}>
      <div className="space-y-3" data-testid="intention-understanding">
        {blocking.length ? (
          <div
            className="rounded-lg border border-state-warning/40 bg-state-warning-soft px-3 py-2.5"
            role="status"
            data-testid="understanding-needs"
          >
            <p className="flex items-center gap-2 text-[0.875rem] font-semibold text-brand-navy">
              <AlertTriangle className="size-4 text-state-warning" aria-hidden="true" />
              {w.needs}
            </p>
            <ul className="mt-1.5 space-y-1 text-[0.8125rem] text-brand-navy">
              {blocking.map((ambiguity) => (
                <li key={ambiguity.kind} data-testid="understanding-question" data-kind={ambiguity.kind}>
                  {questions[ambiguity.kind] ?? ambiguity.said}
                  {ambiguity.options?.length ? (
                    <span className="block text-xs text-shell-muted">
                      {fill(w.options, {
                        options: (ambiguity.options ?? [])
                          .map((o) => goals[o] ?? actions[o] ?? o)
                          .join(", "),
                      })}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
            {intentionId ? (
              <Link
                href={`${routes.intentionNew()}?intention=${intentionId}`}
                className={buttonVariants({ variant: "outline", size: "sm", className: "mt-2" })}
                data-testid="understanding-clarify"
              >
                <PencilLine className="size-3.5" aria-hidden="true" />
                {w.clarify}
              </Link>
            ) : null}
          </div>
        ) : null}

        <dl className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-3 gap-y-2 text-[0.8125rem]">
          <dt className="text-shell-muted">{w.goal}</dt>
          <dd className="text-brand-navy" data-testid="understanding-goal">
            <span className="font-medium">{goals[understanding.goal.code] ?? understanding.goal.code}</span>
            <span className="text-shell-muted"> · {w.mode[understanding.mode]}</span>
            {understanding.goal.said.length ? (
              <span className="block text-xs text-shell-muted">
                {fill(w.said, { said: understanding.goal.said.join(" · ") })}
              </span>
            ) : null}
          </dd>

          {understanding.actions.length ? (
            <>
              <dt className="text-shell-muted">{w.actions}</dt>
              <dd>
                <ul className="space-y-1">
                  {understanding.actions.map((action) => (
                    <li key={action.code} className="text-brand-navy" data-testid="understanding-action">
                      {actions[action.code] ?? action.code}{" "}
                      <span className="text-xs text-shell-muted">
                        {fill(w.said, { said: action.said })}
                      </span>
                      {action.changes_systems ? (
                        <span className="block">
                          <Pill tone="warning">{w.changesSystems}</Pill>
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </dd>
            </>
          ) : null}

          <dt className="text-shell-muted">{w.about}</dt>
          <dd className="text-brand-navy">
            {understanding.entities.length ? (
              <ul className="flex flex-wrap gap-x-3 gap-y-1">
                {understanding.entities.map((entity) => (
                  <li key={entity.entity_id}>
                    <Link
                      href={entityHref({ id: entity.entity_id, type: entity.type })}
                      className="font-medium hover:underline"
                    >
                      {entity.name}
                    </Link>
                    {entity.said ? (
                      <span className="text-xs text-shell-muted">
                        {" "}
                        {fill(w.said, { said: entity.said })}
                      </span>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <span className="text-shell-muted">{w.nothing}</span>
            )}
          </dd>
        </dl>

        {notes.length ? (
          <div className="text-[0.8125rem]">
            <p className="flex items-center gap-1.5 font-medium text-brand-navy">
              <Info className="size-3.5 text-shell-muted" aria-hidden="true" />
              {w.warnings}
            </p>
            <ul className="mt-1 space-y-0.5 text-shell-muted" data-testid="understanding-notes">
              {notes.map((ambiguity) => (
                <li key={ambiguity.kind}>{questions[ambiguity.kind] ?? ambiguity.said}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </Card>
  );
}
