"use client";

import { AlertTriangle, Brain, Info, PencilLine, Sparkles } from "lucide-react";
import Link from "next/link";

import { Card, entityHref } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { exactDate } from "@/components/knowledge/time";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { IntentionDetail } from "@/lib/intentions/api";
import { modelTitle } from "@/lib/models";

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

        {understanding.restated ? (
          <div data-testid="understanding-restated">
            <p className="text-[0.875rem] text-brand-navy">« {understanding.restated} »</p>
            {understanding.read_by?.method === "model" && understanding.read_by.model ? (
              <p className="flex items-center gap-1.5 text-xs text-shell-muted">
                <Sparkles className="size-3.5" aria-hidden="true" />
                {fill(w.readBy, { model: modelTitle(understanding.read_by.model) })}
              </p>
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

        {understanding.scope ? <ScopeSection scope={understanding.scope} /> : null}

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

type Scope = NonNullable<UnderstandingRead["scope"]>;

/** Its scope (LEKA-386): where, when, what is excluded, under what
 * constraints — each with the words that set it. */
function ScopeSection({ scope }: { scope: Scope }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.intentions.understanding.scope;
  const kinds = w.kinds as Record<string, string>;
  const lifecycles = w.lifecycles as Record<string, string>;
  const shown = scope.constraints.filter(
    (c) => c.kind !== "exclude" && c.kind !== "services" && c.kind !== "sources",
  );
  const value = (raw: unknown) =>
    typeof raw === "string" || typeof raw === "number" ? String(raw) : null;
  return (
    <div data-testid="understanding-scope">
      <p className="mb-1.5 text-[0.8125rem] font-semibold text-brand-navy">{w.title}</p>
      <dl className="grid grid-cols-[minmax(0,8rem)_minmax(0,1fr)] gap-x-3 gap-y-2 text-[0.8125rem]">
        <dt className="text-shell-muted">{w.environments}</dt>
        <dd className="text-brand-navy" data-testid="scope-environment">
          {scope.environments.length ? scope.environments.join(", ") : w.everywhere}
          {scope.environment_origin ? (
            <span className="text-xs text-shell-muted"> · {w.origins[scope.environment_origin]}</span>
          ) : null}
        </dd>
        {scope.period ? (
          <>
            <dt className="text-shell-muted">{w.period}</dt>
            <dd className="text-brand-navy" data-testid="scope-period">
              {exactDate(locale, scope.period.since)} → {exactDate(locale, scope.period.until)}
              <span className="block text-xs text-shell-muted">
                {scope.period.explicit
                  ? `${w.explicit}${scope.period.said ? ` : « ${scope.period.said} »` : ""}`
                  : w.byDefault}
              </span>
            </dd>
          </>
        ) : null}
        {scope.excluded.length ? (
          <>
            <dt className="text-shell-muted">{w.excluded}</dt>
            <dd className="text-brand-navy" data-testid="scope-excluded">
              {scope.excluded.map((thing) => thing.name).join(", ")}
            </dd>
          </>
        ) : null}
        {shown.length ? (
          <>
            <dt className="text-shell-muted">{w.constraints}</dt>
            <dd>
              <ul className="flex flex-wrap gap-1.5" data-testid="scope-constraints">
                {shown.map((constraint) => {
                  const said = value(constraint.value);
                  return (
                    <li key={constraint.kind} data-kind={constraint.kind}>
                      <Pill tone={constraint.hard ? "violet" : "neutral"}>
                        {kinds[constraint.kind] ?? constraint.kind}
                        {said && said !== "true" && constraint.kind !== "urgency" ? ` : ${said}` : ""}
                      </Pill>
                    </li>
                  );
                })}
              </ul>
            </dd>
          </>
        ) : null}
        {scope.entities.some((e) => e.lifecycle && e.lifecycle !== "active") ? (
          <>
            <dt className="text-shell-muted">{t.intentions.understanding.about}</dt>
            <dd className="text-brand-navy">
              {scope.entities
                .filter((e) => e.lifecycle && e.lifecycle !== "active")
                .map((e) => `${e.name} (${lifecycles[e.lifecycle ?? ""] ?? e.lifecycle})`)
                .join(", ")}
            </dd>
          </>
        ) : null}
      </dl>
    </div>
  );
}
