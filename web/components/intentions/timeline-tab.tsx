"use client";

import { History } from "lucide-react";
import { useState } from "react";

import { cn } from "cn";

import { Card, type TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { exactDate } from "@/components/knowledge/time";
import { useCurrentUser } from "@/components/shell/shell-provider";
import { ErrorState } from "@/components/states/error-state";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { IntentionEvent } from "@/lib/intentions/api";
import { TIMELINE_CATEGORIES, type TimelineCategory, type TimelineItem } from "@/lib/outcomes";
import { useTimeline } from "@/lib/outcomes-queries";

/**
 * An intention's tab Historique (LEKA-384, then LEKA-392): its whole story
 * in one timeline — what happened to it, its analyses, its decision and
 * every vote, its plan and every step, its outcome — each said by who,
 * LEKA or a person, when, and why (GET /intentions/{id}/timeline) — told
 * in order, the latest last, the cause before what it moved. Filtered by
 * kind of thing and by who. Read from records kept append-only: nothing is
 * shown that they do not say.
 */

const CATEGORY_TONES: Record<TimelineCategory, TileTone> = {
  intention: "neutral",
  analysis: "info",
  decision: "warning",
  action: "violet",
  outcome: "success",
};

/** One event of its history, in words. */
export function eventSaid(
  t: Dictionary,
  event: Pick<IntentionEvent, "kind" | "name" | "detail" | "from_status" | "to_status">,
): string {
  const w = t.intentions.history;
  const detail = event.detail as Record<string, unknown>;
  const kinds = t.intentions.linkKinds as Record<string, string>;
  switch (event.kind) {
    case "created":
      return w.created;
    case "linked":
    case "unlinked":
      return fill(w[event.kind], {
        kind: kinds[String(detail.kind)] ?? String(detail.kind),
        label: String(detail.label ?? ""),
      });
    case "archived":
    case "restored":
      return w[event.kind];
    case "moved": {
      const named = event.name ? (w.names as Record<string, string>)[event.name] : undefined;
      if (named) return named;
      const statuses = t.intentions.statuses as Record<string, string>;
      return fill(w.moved, {
        from: statuses[event.from_status ?? ""] ?? "",
        to: statuses[event.to_status ?? ""] ?? "",
      });
    }
    default:
      return event.kind;
  }
}

/** One moment of its story, in words. */
export function itemSaid(t: Dictionary, item: TimelineItem): string {
  const detail = item.detail as Record<string, unknown>;
  if (item.category === "intention") {
    // As its history keeps it: the event, and a move's name.
    const kind = String(detail.event ?? item.kind) as IntentionEvent["kind"];
    return eventSaid(t, {
      kind,
      name: item.kind !== kind ? item.kind : null,
      detail: item.detail ?? {},
      from_status: (detail.from_status ?? null) as IntentionEvent["from_status"],
      to_status: (detail.to_status ?? null) as IntentionEvent["to_status"],
    });
  }
  if (item.category === "analysis" || item.category === "decision") {
    return (t.intentions.history.kinds as Record<string, string>)[item.kind] ?? item.kind;
  }
  return (t.execution.events as Record<string, string>)[item.kind] ?? item.kind;
}

/** What else it says: which analysis, which decision, how much was met. */
function itemMore(t: Dictionary, item: TimelineItem): string | null {
  const w = t.intentions.history;
  const detail = item.detail as Record<string, unknown>;
  if (item.category === "analysis" && typeof detail.number === "number") {
    return fill(w.analysisNumber, { number: detail.number });
  }
  if (item.kind === "decision_opened" && typeof detail.number === "number") {
    return fill(w.decisionNumber, { number: detail.number });
  }
  if (
    item.kind.startsWith("verification_") &&
    typeof detail.met === "number" &&
    typeof detail.expected === "number" &&
    detail.expected > 0
  ) {
    return fill(w.met, { met: detail.met, expected: detail.expected });
  }
  if (typeof detail.version === "number") return fill(w.version, { version: detail.version });
  return null;
}

function Chip({
  active,
  onClick,
  children,
  testId,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      data-testid={testId}
      className={cn(
        "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
        active
          ? "border-shell-nav-active bg-brand-violet-soft text-shell-nav-active"
          : "border-shell-line bg-white text-shell-nav hover:bg-shell-canvas",
      )}
    >
      {children}
    </button>
  );
}

export function TimelineTab({ id }: { id: string }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const me = useCurrentUser();
  const w = t.intentions.history;
  const [categories, setCategories] = useState<TimelineCategory[]>([]);
  const [actor, setActor] = useState<"person" | "system" | null>(null);
  const timeline = useTimeline(id, { categories, actor });
  const filtered = categories.length > 0 || actor !== null;

  function toggle(category: TimelineCategory) {
    setCategories((before) =>
      before.includes(category) ? before.filter((c) => c !== category) : [...before, category],
    );
  }

  const filters = (
    <div className="mb-4 flex flex-col gap-2" role="group" aria-label={w.filters}>
      <div className="flex flex-wrap gap-1.5" data-testid="timeline-categories">
        <Chip active={categories.length === 0} onClick={() => setCategories([])}>
          {w.all}
        </Chip>
        {TIMELINE_CATEGORIES.map((category) => (
          <Chip
            key={category}
            active={categories.includes(category)}
            onClick={() => toggle(category)}
            testId={`timeline-category-${category}`}
          >
            {w.categories[category]}
          </Chip>
        ))}
      </div>
      <div className="flex flex-wrap gap-1.5" data-testid="timeline-actors">
        {(["all", "person", "system"] as const).map((option) => (
          <Chip
            key={option}
            active={(actor ?? "all") === option}
            onClick={() => setActor(option === "all" ? null : option)}
            testId={`timeline-actor-${option}`}
          >
            {w.actors[option]}
          </Chip>
        ))}
      </div>
    </div>
  );

  let body: React.ReactNode;
  if (timeline.isError) {
    body = <ErrorState error={timeline.error} onRetry={() => void timeline.refetch()} />;
  } else if (!timeline.data) {
    body = <div className="h-64 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  } else if (timeline.data.length === 0) {
    body = <p className="text-[0.8125rem] text-shell-muted">{filtered ? w.emptyFiltered : w.empty}</p>;
  } else {
    body = (
      <ol className="relative space-y-4 border-l border-shell-line pl-5" data-testid="intention-history">
        {[...timeline.data].reverse().map((item) => {
          const who =
            item.actor === "system"
              ? w.leka
              : item.by && item.by === me?.id
                ? fill(w.by, { name: t.intentions.you })
                : item.by_name
                  ? fill(w.by, { name: item.by_name })
                  : w.someone;
          const more = itemMore(t, item);
          return (
            <li
              key={item.id}
              className="relative"
              data-testid="intention-event"
              data-category={item.category}
              data-kind={item.kind}
            >
              <span
                aria-hidden="true"
                className="absolute top-1.5 -left-[1.6rem] size-2.5 rounded-full border-2 border-white bg-brand-violet"
              />
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-[0.875rem] font-medium text-brand-navy">{itemSaid(t, item)}</p>
                <Pill tone={CATEGORY_TONES[item.category]}>{w.categories[item.category]}</Pill>
              </div>
              <p className="text-xs text-shell-muted">
                <time dateTime={item.at}>{exactDate(locale, item.at)}</time> · {who}
                {more ? ` · ${more}` : ""}
              </p>
              {item.reason ? (
                <p className="mt-0.5 text-xs text-brand-navy">{fill(w.reason, { reason: item.reason })}</p>
              ) : null}
            </li>
          );
        })}
      </ol>
    );
  }

  return (
    <Card title={w.title} icon={<History className="size-4 text-shell-muted" aria-hidden="true" />}>
      {filters}
      {body}
    </Card>
  );
}
