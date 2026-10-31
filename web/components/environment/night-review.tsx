"use client";

import { Loader2, MoonStar, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { cn } from "cn";

import { Card, IconTile } from "@/components/environment/parts";
import { intentionHref } from "@/components/environment/twin";
import { hrefOf } from "@/components/insights/leka-insights";
import { Pill } from "@/components/intelligence/pill";
import { exactDate, timeAgo } from "@/components/knowledge/time";
import { Button } from "@/components/ui/button";
import { useNightReview, useNightReviewAgain } from "@/lib/environment-queries";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import type { NightPoint } from "@/lib/twin";

/**
 * The night review (2026-10-29): what LEKA went through overnight — every
 * hour of the night — how many things, sources, alerts, findings — and what
 * it found to look at, the most serious first, each with where to see it
 * and, when LEKA can look into it, a question ready to ask. What was settled
 * since is gone, said in a word (2026-10-31). Gone through again on demand.
 */

const TONES = { high: "danger", medium: "warning", low: "neutral" } as const;

/** Where a point is seen: a finding where its subject is (its entity's
 * sheet, its source's page), as Ce que LEKA a remarqué links it
 * (2026-10-31: « Voir » led to the page already open) — else the review's. */
export function seenAt(point: NightPoint): string {
  if (point.kind !== "finding") return point.href;
  const params = point.params as Record<string, unknown>;
  const href = hrefOf({
    code: String(params.code ?? ""),
    category: String(params.category ?? ""),
    subject: {
      type: String(params.subject_type ?? ""),
      id: params.subject_id ? String(params.subject_id) : null,
      kind: params.subject_kind ? String(params.subject_kind) : null,
    },
  } as unknown as Parameters<typeof hrefOf>[0]);
  return href ?? point.href;
}
const SHOWN = 6;

/** What a point says, in the reader's language. */
export function pointSaid(t: Dictionary, point: NightPoint): string {
  const w = t.environment.night.points;
  const params = point.params as Record<string, unknown>;
  switch (point.kind) {
    case "alert":
      return fill(w.alert, {
        name: point.name,
        trouble: (w.troubles as Record<string, string>)[String(params.trouble)] ?? String(params.trouble),
      });
    case "source":
      return fill(w.source, {
        name: point.name,
        why: (w.whys as Record<string, string>)[String(params.why)] ?? String(params.why),
      });
    case "finding":
      return fill(w.finding, { name: point.name });
    case "run":
      return fill(w.run, { name: point.name, count: point.count });
    case "findings": {
      const names = Array.isArray(params.names) ? params.names.map(String).join(", ") : "";
      return fill(names ? w.findingsOn : w.findings, { count: point.count, names });
    }
    case "change":
      return fill(w.change, { number: String(params.number ?? ""), name: point.name });
    default:
      return fill((w as unknown as Record<string, string>)[point.kind] ?? point.kind, {
        count: point.count,
      });
  }
}

/** The question LEKA is asked about a point, when it can look into it. */
function askOf(t: Dictionary, point: NightPoint): string | null {
  if (!point.ask) return null;
  const w = t.environment.night;
  if (point.kind === "finding") return fill(w.askFinding, { name: point.name });
  const trouble = String((point.params as Record<string, unknown>).trouble ?? "");
  return fill(w.ask, {
    name: point.name,
    trouble: (w.points.troubles as Record<string, string>)[trouble] ?? trouble,
  });
}

export function NightReviewCard({ className }: { className?: string }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.environment.night;
  const review = useNightReview();
  const again = useNightReviewAgain();
  const [all, setAll] = useState(false);
  const found = review.data;

  async function goAgain() {
    try {
      await again.mutateAsync();
    } catch {
      notify.error({ title: w.failed });
    }
  }

  const relaunch = (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() => void goAgain()}
      disabled={again.isPending}
      data-testid="night-review-again"
    >
      {again.isPending ? (
        <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
      ) : (
        <RefreshCw className="size-3.5" aria-hidden="true" />
      )}
      {w.again}
    </Button>
  );

  const points = found?.points ?? [];
  const shown = all ? points : points.slice(0, SHOWN);
  const checked = found?.checked ?? {};
  return (
    <Card
      title={w.title}
      icon={<IconTile icon={MoonStar} tone="violet" className="size-9" />}
      action={relaunch}
      className={className}
    >
      <div data-testid="night-review" className="flex flex-col gap-3">
        {found === null ? (
          <p className="text-[0.8125rem] text-shell-muted">{w.first}</p>
        ) : found ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Pill tone={points.length ? "warning" : "success"} data-testid="night-review-verdict">
                {points.length ? fill(w.toLook, { count: points.length }) : w.nothing}
              </Pill>
              <span className="text-[0.8125rem] text-shell-muted" data-testid="night-review-checked">
                {fill(found.trigger === "asked" ? w.checkedAsked : w.checkedNight, {
                  when: found.trigger === "asked" ? timeAgo(t, found.at).toLowerCase() : exactDate(locale, found.at),
                  things: checked.things ?? 0,
                  sources: checked.sources ?? 0,
                  alerts: checked.alerts ?? 0,
                  findings: checked.findings ?? 0,
                })}
                {found.settled ? ` ${fill(w.settled, { count: found.settled })}` : ""}
              </span>
            </div>
            {points.length ? (
              <ul className="divide-y divide-shell-line/60" data-testid="night-review-points">
                {shown.map((point, index) => {
                  const ask = askOf(t, point);
                  return (
                    <li
                      key={`${point.kind}-${point.name}-${index}`}
                      className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2"
                      data-testid="night-review-point"
                      data-kind={point.kind}
                    >
                      <span
                        aria-hidden="true"
                        className={cn(
                          "size-2 shrink-0 rounded-full",
                          point.severity === "high"
                            ? "bg-state-danger"
                            : point.severity === "medium"
                              ? "bg-state-warning"
                              : "bg-shell-muted",
                        )}
                      />
                      <span className="min-w-0 flex-1 text-[0.875rem] text-brand-navy">
                        {pointSaid(t, point)}
                      </span>
                      <Pill tone={TONES[point.severity]}>{w.severities[point.severity]}</Pill>
                      {ask ? (
                        <Link
                          href={intentionHref(ask)}
                          className="text-[0.8125rem] font-medium text-brand-violet hover:underline"
                        >
                          {w.analyse}
                        </Link>
                      ) : null}
                      {seenAt(point).startsWith("http") ? (
                        <a
                          href={seenAt(point)}
                          target="_blank"
                          rel="noreferrer"
                          className="text-[0.8125rem] font-medium text-brand-violet hover:underline"
                        >
                          {w.see}
                        </a>
                      ) : (
                        <Link
                          href={seenAt(point)}
                          className="text-[0.8125rem] font-medium text-brand-violet hover:underline"
                        >
                          {w.see}
                        </Link>
                      )}
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="text-[0.8125rem] text-shell-muted">{w.allGood}</p>
            )}
            {points.length > SHOWN ? (
              <button
                type="button"
                onClick={() => setAll(!all)}
                className="self-start text-[0.8125rem] font-medium text-brand-violet hover:underline"
              >
                {all ? w.fewer : fill(w.more, { count: points.length - SHOWN })}
              </button>
            ) : null}
          </>
        ) : (
          <div className="h-16 animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />
        )}
      </div>
    </Card>
  );
}
