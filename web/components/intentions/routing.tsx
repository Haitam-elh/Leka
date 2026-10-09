"use client";

import { Compass, RefreshCw } from "lucide-react";
import Link from "next/link";

import { RunAgent } from "@/components/capabilities/agent-runs";
import { reasonSaid, titleOf } from "@/components/capabilities/catalogue";
import { Card, type TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { Button } from "@/components/ui/button";
import { routes } from "@/config/routes";
import type { CapabilityReason } from "@/lib/capabilities";
import { useCapability } from "@/lib/capabilities-queries";
import { fill, type Dictionary } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { RoutedCandidate, Routing } from "@/lib/intentions/api";
import { useIntentionRouting, useRouteAgain } from "@/lib/intentions/queries";

/**
 * Where an intention goes (LEKA-398): the capability LEKA chose for it —
 * an agent offered to run, with what it must be asked — every one it
 * considered, ranked, each with the signals behind its score; every one it
 * left out, said why; or LEKA's own analysis when nothing else fits; or what
 * to ask when the intention is not clear. Routed again on demand.
 */

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

function SelectedAgent({ candidate, intentionId }: { candidate: RoutedCandidate; intentionId: string }) {
  const { data } = useCapability(candidate.key);
  if (!data) return null;
  return <RunAgent capability={data} intentionId={intentionId} />;
}

export function RoutingPanel({ intentionId }: { intentionId: string }) {
  const t = useDictionary();
  const w = t.intentions.routing;
  const { data } = useIntentionRouting(intentionId);
  const again = useRouteAgain(intentionId);
  if (!data) return null;
  const titles = new Map(
    [...data.candidates, ...data.excluded].map((c) => [c.key, titleOf(t, c)] as const),
  );
  const selected = data.candidates.filter((c) => c.selected);
  const agents = selected.filter((c) => c.kind === "agent");
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
          {data.outcome === "clarify" && (data.questions.length || data.suggestions.length) ? (
            <div className="text-[0.8125rem]" data-testid="routing-clarify">
              {data.questions.map((q) => (
                <p key={q} className="text-brand-navy">
                  {q}
                </p>
              ))}
              {data.suggestions.length ? (
                <p className="text-shell-muted">
                  {fill(w.suggestions, {
                    titles: data.suggestions.map((k) => titles.get(k) ?? k).join(", "),
                  })}
                </p>
              ) : null}
            </div>
          ) : null}
          {data.candidates.length ? (
            <ol className="space-y-2 text-[0.8125rem]" data-testid="routing-candidates">
              {data.candidates.map((c) => (
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
          {data.excluded.length ? (
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
      {agents.map((c) => (
        <SelectedAgent key={c.key} candidate={c} intentionId={intentionId} />
      ))}
    </div>
  );
}
