"use client";

import { useQueries } from "@tanstack/react-query";
import { ChevronDown, Compass, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AgentRuns, RunAgent, suggestedInputs } from "@/components/capabilities/agent-runs";
import { CodeChanges } from "@/components/capabilities/code-changes";
import { reasonSaid, titleOf } from "@/components/capabilities/catalogue";
import { WorkflowPanel } from "@/components/capabilities/workflow-runs";
import { Card, type TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { Button } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { capabilities, type CapabilityDetail, type CapabilityReason } from "@/lib/capabilities";
import { capabilityKeys } from "@/lib/capabilities-queries";
import { fill, type Dictionary } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { RoutedCandidate, Routing } from "@/lib/intentions/api";
import { useIntention, useIntentionRouting, useRouteAgain } from "@/lib/intentions/queries";

/**
 * Where an intention goes (LEKA-398): the capability LEKA chose for it —
 * an agent offered to run, with what it must be asked — every one it
 * considered, ranked, each with the signals behind its score; every one it
 * left out, said why; or LEKA's own analysis when nothing else fits; or what
 * to ask when the intention is not clear. Routed again on demand.
 */

/** The best ones shown, the rest on demand (2026-10-29: thirty, with their
 * signals, ran down the page). */
const SHOWN = 5;

const TONES: Record<Routing["outcome"], TileTone> = {
  routed: "success",
  fallback: "neutral",
  clarify: "warning",
};

export function signalsSaid(t: Dictionary, candidate: RoutedCandidate): string {
  const w = t.intentions.routing.signals as Record<string, string>;
  return candidate.signals
    .map((s) => fill(w[s.code] ?? s.code, { detail: s.detail ?? "" }))
    .join(" · ");
}

function excludedSaid(t: Dictionary, candidate: RoutedCandidate): string {
  return candidate.reasons
    .map((reason) =>
      reason.code === "policy"
        ? t.intentions.routing.policy
        : reasonSaid(t, { code: String(reason.code), detail: reason } as CapabilityReason),
    )
    .join(" · ");
}


export function RoutingPanel({ intentionId }: { intentionId: string }) {
  const t = useDictionary();
  const w = t.intentions.routing;
  const { data } = useIntentionRouting(intentionId);
  const again = useRouteAgain(intentionId);
  const [all, setAll] = useState(false);
  // Why these agents: the ranking, read on demand (2026-11-07: scores and
  // signals, shown to everyone, read as the thing to act on).
  const [why, setWhy] = useState(false);
  const { data: intention } = useIntention(intentionId);
  const chosen = useQueries({
    queries: (data?.candidates ?? [])
      .filter((c) => c.selected && (c.kind === "agent" || c.kind === "workflow"))
      .map((c) => ({ queryKey: capabilityKeys.one(c.key), queryFn: () => capabilities.one(c.key) })),
  })
    .map((q) => q.data)
    .filter((c): c is CapabilityDetail => Boolean(c));
  if (!data) return null;
  const titles = new Map(
    [...data.candidates, ...data.excluded].map((c) => [c.key, titleOf(t, c)] as const),
  );
  const selected = data.candidates.filter((c) => c.selected);
  // What a person runs for it: an agent, a line each; a workflow, its panel
  // (LEKA-397).
  const agents = chosen.filter((c) => c.kind !== "workflow");
  const workflows = chosen.filter((c) => c.kind === "workflow");
  const headline =
    data.outcome === "routed"
      ? fill(w.routed, { titles: selected.map((c) => titleOf(t, c)).join(", ") })
      : data.outcome === "fallback"
        ? (w.fallbacks as Record<string, string>)[data.why ?? "no_match"] ?? w.fallbacks.no_match
        : (w.clarifies as Record<string, string>)[data.why ?? "unclear"] ?? w.clarifies.unclear;

  return (
    <div className="flex flex-col gap-4">
      <Card
        title={w.title}
        icon={<Compass className="size-4 text-shell-muted" aria-hidden="true" />}
        action={
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={again.isPending}
            onClick={() => again.mutate()}
          >
            <RefreshCw className="size-3.5" aria-hidden="true" />
            {w.again}
          </Button>
        }
      >
        <div data-testid="intention-routing" data-outcome={data.outcome} className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Pill tone={TONES[data.outcome]}>{w.outcomes[data.outcome]}</Pill>
            <span className="text-[0.875rem] text-brand-navy">{headline}</span>
          </div>
          {/* What to answer is asked once, in the brief, in its asker's
              language: never the router's own words here. */}
          {data.outcome === "clarify" && data.suggestions.length ? (
            <p className="text-[0.8125rem] text-shell-muted" data-testid="routing-clarify">
              {fill(w.suggestions, {
                titles: data.suggestions.map((k) => titles.get(k) ?? k).join(", "),
              })}
            </p>
          ) : null}
          {agents.length ? (
            <div className="flex flex-col gap-2" data-testid="routing-agents">
              {agents.map((capability) => (
                <RunAgent
                  key={`${capability.key}-${intention ? "prefilled" : "empty"}`}
                  capability={capability}
                  intentionId={intentionId}
                  prefill={suggestedInputs(capability.inputs, intention)}
                  compact
                />
              ))}
              <p className="text-xs text-shell-muted">{t.agentRuns.readOnly}</p>
            </div>
          ) : null}
          {data.candidates.length || data.excluded.length ? (
            <button
              type="button"
              aria-expanded={why}
              onClick={() => setWhy(!why)}
              className="flex items-center gap-1 self-start text-[0.8125rem] font-medium text-brand-violet hover:underline"
              data-testid="routing-why"
            >
              <ChevronDown
                className={`size-3.5 transition-transform duration-150 motion-reduce:transition-none ${why ? "" : "-rotate-90"}`}
                aria-hidden="true"
              />
              {w.why}
            </button>
          ) : null}
          {why && data.candidates.length ? (
            <ol className="space-y-2 text-[0.8125rem]" data-testid="routing-candidates">
              {(all ? data.candidates : data.candidates.slice(0, SHOWN)).map((c) => (
                <li key={c.key} data-key={c.key} className="flex flex-col">
                  <span className="flex flex-wrap items-center gap-2">
                    <Link
                      href={routes.capability(c.key)}
                      className="font-medium text-brand-navy hover:underline"
                    >
                      {titleOf(t, c)}
                    </Link>
                    <span className="text-shell-muted">{fill(w.score, { score: c.score })}</span>
                    {c.selected ? <Pill tone="success">{w.chosen}</Pill> : null}
                    {!c.eligible ? <Pill tone="neutral">{w.weak}</Pill> : null}
                  </span>
                  <span className="text-xs text-shell-muted">{signalsSaid(t, c)}</span>
                </li>
              ))}
            </ol>
          ) : null}
          {why && data.candidates.length > SHOWN ? (
            <button
              type="button"
              onClick={() => setAll(!all)}
              className="self-start text-[0.8125rem] font-medium text-brand-violet hover:underline"
              data-testid="routing-more"
            >
              {all ? w.fewer : fill(w.more, { count: data.candidates.length - SHOWN })}
            </button>
          ) : null}
          {why && data.excluded.length ? (
            <div>
              <p className="mb-1 text-xs font-semibold text-shell-muted">{w.excluded}</p>
              <ul className="space-y-1 text-xs" data-testid="routing-excluded">
                {data.excluded.map((c) => (
                  <li key={c.key} data-key={c.key} className="text-brand-navy">
                    {titleOf(t, c)} <span className="text-state-warning">· {excludedSaid(t, c)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </Card>
      {workflows.map((capability) => (
        <WorkflowPanel key={capability.key} capability={capability} intentionId={intentionId} />
      ))}
      {/* Every agent's runs for it, and what they propose to change in code:
          once each, whichever agent ran (2026-11-07: a pair per agent). */}
      {agents.length ? <AgentRuns intentionId={intentionId} /> : null}
      {agents.some((c) => c.formats.includes("diff")) ? <CodeChanges intentionId={intentionId} /> : null}
    </div>
  );
}
