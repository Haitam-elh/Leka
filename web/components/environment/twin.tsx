"use client";

import {
  ArrowRight,
  Bell,
  CircleCheck,
  CircleX,
  Clock,
  type LucideIcon,
  RefreshCw,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import Link from "next/link";

import { cn } from "cn";

import { Card, CardLink, entityHref, IconTile, typeLabel } from "@/components/environment/parts";
import { KnowledgeTable, type KnowledgeColumn } from "@/components/knowledge/knowledge-table";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { TONES } from "@/components/knowledge/status";
import { timeAgo } from "@/components/knowledge/time";
import { routes } from "@/config/routes";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { EnvironmentNode } from "@/lib/environment";
import {
  type Alert,
  byState,
  type Monitoring,
  TWIN_STATES,
  type TwinCoverage,
  type TwinFreshness,
  type TwinSource,
  type TwinState,
  type TwinStateName,
} from "@/lib/twin";

/**
 * The Digital Twin (LEKA-442), drawn: each thing's state in the same six
 * words everywhere, with what it rests on and how fresh — and the watch
 * the plan includes. « Inconnu » never reads « sain »; nothing is said
 * real-time that is not; an alert the plan does not include is never
 * simulated: the limit is said, with the plan that lifts it.
 */

const STATE_TONE: Record<TwinStateName, keyof typeof TONES> = {
  unavailable: "danger",
  degraded: "warning",
  stale: "info",
  unknown: "neutral",
  not_covered: "neutral",
  operational: "success",
};

/** « il y a 7 min », inside a sentence. */
function ago(t: ReturnType<typeof useDictionary>, iso: string): string {
  const said = timeAgo(t, iso);
  return said.charAt(0).toLowerCase() + said.slice(1);
}

/** A link to a new intention, its words written for the person. */
export function intentionHref(words: string): string {
  return `${routes.intentionNew()}?q=${encodeURIComponent(words)}`;
}

/** The six states, each with what it means — a legend that defines. */
export function TwinLegend({ className }: { className?: string }) {
  const t = useDictionary();
  const w = t.environment.twin;
  return (
    <ul
      aria-label={w.legend}
      className={cn("flex flex-wrap gap-x-4 gap-y-1 text-[0.8125rem] text-brand-navy", className)}
      data-testid="twin-legend"
    >
      {TWIN_STATES.map((state) => (
        <li key={state} className="flex items-center gap-1.5" title={w.definitions[state]}>
          <span
            aria-hidden="true"
            className={cn("size-2.5 rounded-full", TONES[STATE_TONE[state]].dot)}
          />
          {w.states[state]}
          <span className="sr-only"> : {w.definitions[state]}</span>
        </li>
      ))}
    </ul>
  );
}

/** When it was last read, how often — never « temps réel » — and late. */
export function FreshnessLine({ freshness }: { freshness: TwinFreshness | null | undefined }) {
  const t = useDictionary();
  const w = t.environment.twin.freshness;
  if (!freshness) return null;
  const read = freshness.last_read_at;
  return (
    <p className="flex items-start gap-2 text-xs text-shell-muted" data-testid="twin-freshness">
      <span
        aria-hidden="true"
        className={cn(
          "mt-1 size-2.5 shrink-0 rounded-full",
          !read ? "bg-shell-muted" : freshness.late ? "bg-state-warning" : "bg-state-success",
        )}
      />
      <span>
        <span className="block font-medium text-brand-navy">
          {read ? fill(w.read, { ago: ago(t, read) }) : w.never}
          {freshness.late ? (
            <span className="ms-2 text-state-warning" data-testid="twin-late">
              {w.late}
            </span>
          ) : null}
        </span>
        <span className="block">
          {fill(w.every, { minutes: freshness.every_minutes })}
          {freshness.webhooks ? ` · ${w.webhooks}` : ""}
        </span>
      </span>
    </p>
  );
}

/** A thing's state as a badge: its word, its colour, its icon. */
export function TwinBadge({ state, size = "md" }: { state: TwinStateName; size?: "sm" | "md" }) {
  return <StatusBadge variant={`entity.${state}`} size={size} />;
}

/** How a state is known, in words: « mesuré par acme-eu · confirmé ». */
export function twinHow(t: ReturnType<typeof useDictionary>, twin: TwinState): string {
  const w = t.environment.twin;
  const reason = fill((w.reasons as Record<string, string>)[twin.reason] ?? twin.reason, {
    key: twin.incident?.key ?? "",
  });
  return [
    reason,
    w.basis[twin.basis],
    twin.signal.length ? fill(w.by, { sources: twin.signal.join(", ") }) : null,
    twin.certainty !== "confirmed" ? w.certainty[twin.certainty] : null,
    twin.was ? fill(w.was, { state: w.states[twin.was].toLowerCase() }) : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The words of an intention about a thing in this state. */
export function askAbout(
  t: ReturnType<typeof useDictionary>,
  name: string,
  state: TwinStateName,
): string {
  const w = t.environment.twin.ask;
  if (state === "unavailable" || state === "degraded")
    return fill(w.trouble, { name, state: t.environment.twin.states[state].toLowerCase() });
  if (state === "stale") return fill(w.stale, { name });
  return fill(w.state, { name });
}

/** How many things are in each state; each a way to the list of them. */
export function TwinCounts({
  states,
  active,
  onPick,
}: {
  states: Readonly<Record<string, number>>;
  active?: TwinStateName | null;
  onPick?: (state: TwinStateName | null) => void;
}) {
  const t = useDictionary();
  const w = t.environment.twin;
  const total = Object.values(states).reduce((sum, n) => sum + n, 0);
  if (total === 0) {
    return <p className="text-[0.8125rem] text-shell-muted">{w.counts.empty}</p>;
  }
  return (
    <ul className="flex flex-wrap gap-2" aria-label={w.counts.title} data-testid="twin-counts">
      {TWIN_STATES.map((state) => {
        const count = states[state] ?? 0;
        const body = (
          <>
            <span aria-hidden="true" className={cn("size-2 rounded-full", TONES[STATE_TONE[state]].dot)} />
            <span className="font-semibold tabular-nums">{count}</span>
            <span>{w.states[state]}</span>
          </>
        );
        const look = cn(
          "flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[0.8125rem] text-brand-navy",
          active === state ? "border-brand-violet/60 bg-brand-violet-soft" : "border-shell-line bg-white",
          count === 0 && "opacity-60",
        );
        return (
          <li key={state} data-state={state} title={w.definitions[state]}>
            {onPick ? (
              <button
                type="button"
                aria-pressed={active === state}
                onClick={() => onPick(active === state ? null : state)}
                className={cn(look, "outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40")}
              >
                {body}
              </button>
            ) : (
              <span className={look}>{body}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** The readable alternative to the map: every thing with a state, the
 * worst first — its state, how it is known, when last observed, and the
 * way to ask LEKA about it. */
export function TwinList({
  nodes,
  filter,
}: {
  nodes: readonly EnvironmentNode[];
  filter?: TwinStateName | null;
}) {
  const t = useDictionary();
  const w = t.environment.twin.list;
  const rows = byState(
    nodes.filter((node) => node.twin && (!filter || node.twin.state === filter)),
  );
  const columns: KnowledgeColumn<EnvironmentNode>[] = [
    {
      id: "name",
      header: w.name,
      sortValue: (node) => node.name,
      cell: (node) =>
        node.entity_id ? (
          <Link
            href={entityHref({ id: node.entity_id, type: node.type })}
            className="font-medium text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          >
            {node.name}
          </Link>
        ) : (
          <span className="font-medium text-brand-navy">{node.name}</span>
        ),
    },
    { id: "type", header: w.type, cell: (node) => typeLabel(t, node.type) },
    {
      id: "state",
      header: w.state,
      sortValue: (node) => (node.twin ? TWIN_STATES.indexOf(node.twin.state) : 9),
      cell: (node) => (node.twin ? <TwinBadge state={node.twin.state} size="sm" /> : null),
    },
    {
      id: "how",
      header: w.how,
      cell: (node) =>
        node.twin ? <span className="text-xs text-shell-muted">{twinHow(t, node.twin)}</span> : null,
    },
    {
      id: "observed",
      header: w.observed,
      sortValue: (node) => node.twin?.observed_at ?? "",
      cell: (node) =>
        node.twin?.observed_at ? (
          <span className="text-xs">{timeAgo(t, node.twin.observed_at)}</span>
        ) : (
          <span className="text-xs text-shell-muted">{w.never}</span>
        ),
    },
    {
      id: "ask",
      header: w.ask,
      cell: (node) =>
        node.twin ? (
          <Link
            href={intentionHref(askAbout(t, node.name, node.twin.state))}
            className="inline-flex items-center gap-1 text-xs font-medium text-shell-nav-active hover:underline"
          >
            <Sparkles className="size-3.5" aria-hidden="true" />
            {w.ask}
          </Link>
        ) : null,
    },
  ];
  return (
    <div data-testid="twin-list">
      <KnowledgeTable
        caption={w.caption}
        columns={columns}
        rows={rows}
        rowKey={(node) => node.id}
        empty={{ title: w.none }}
      />
    </div>
  );
}

const SOURCE_LOOK: Record<TwinSource["state"], LucideIcon> = {
  read: CircleCheck,
  error: CircleX,
  degraded: TriangleAlert,
  stale: Clock,
  syncing: RefreshCw,
  disabled: CircleX,
  never: Clock,
};

/** What covers each part of the twin, and each source in its state — when
 * it was read, what failed. */
export function SourcesCoverage({
  coverage,
  sources,
}: {
  coverage: readonly TwinCoverage[];
  sources: readonly TwinSource[];
}) {
  const t = useDictionary();
  const w = t.environment.twin.coverage;
  const names = new Map(sources.map((s) => [s.id, s.name]));
  return (
    <Card
      title={w.title}
      action={<CardLink href={routes.sources()}>{t.environment.kpi.seeAll}</CardLink>}
    >
      <ul className="space-y-1.5 text-[0.8125rem]" data-testid="twin-coverage">
        {coverage.map((part) => (
          <li key={part.part} className="flex items-start gap-2" data-covered={part.covered}>
            {part.covered ? (
              <CircleCheck className="mt-0.5 size-4 shrink-0 text-state-success" aria-hidden="true" />
            ) : (
              <span aria-hidden="true" className="mt-1 ms-0.5 size-3 shrink-0 rounded-full border border-dashed border-shell-muted" />
            )}
            <span className="min-w-0">
              <span className="font-medium text-brand-navy">{w.parts[part.part]}</span>{" "}
              <span className="text-shell-muted">
                {part.covered
                  ? fill(w.covered, {
                      sources: part.sources.map((id) => names.get(id) ?? "").filter(Boolean).join(", "),
                    })
                  : w.notCovered}
              </span>
            </span>
          </li>
        ))}
      </ul>
      <h3 className="mt-4 mb-2 text-[0.875rem] font-semibold text-brand-navy">{w.sources}</h3>
      <ul className="space-y-1.5 text-[0.8125rem]" data-testid="twin-sources">
        {sources.map((source) => {
          const Icon = SOURCE_LOOK[source.state];
          return (
            <li key={source.id} className="flex items-start gap-2" data-state={source.state}>
              <Icon
                className={cn(
                  "mt-0.5 size-4 shrink-0",
                  source.state === "read"
                    ? "text-state-success"
                    : source.state === "error"
                      ? "text-state-danger"
                      : "text-state-warning",
                )}
                aria-hidden="true"
              />
              <span className="min-w-0">
                <span className="font-medium text-brand-navy">{source.name}</span>{" "}
                <span className="text-shell-muted">
                  {w.states[source.state]}
                  {" · "}
                  {source.last_synced_at
                    ? fill(w.lastRead, { ago: ago(t, source.last_synced_at) })
                    : w.neverRead}
                </span>
                {source.error ? (
                  <span className="block text-xs text-state-danger">{source.error}</span>
                ) : null}
              </span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function AlertRow({ alert }: { alert: Alert }) {
  const t = useDictionary();
  const w = t.environment.twin.alerts;
  const incident = (alert.detail?.incident ?? null) as { key?: string } | null;
  const words =
    alert.kind === "source_failing"
      ? fill(t.environment.twin.ask.source, { name: alert.subject_name })
      : fill(t.environment.twin.ask.trouble, {
          name: alert.subject_name,
          state: w.kinds[alert.kind].toLowerCase(),
        });
  return (
    <li className="flex items-start gap-3 py-2" data-testid="alert" data-kind={alert.kind} data-status={alert.status}>
      <span
        aria-hidden="true"
        className={cn(
          "mt-1.5 size-2.5 shrink-0 rounded-full",
          alert.status !== "open"
            ? "bg-state-success"
            : alert.severity === "high"
              ? "bg-state-danger"
              : "bg-state-warning",
        )}
      />
      <div className="min-w-0 flex-1 text-[0.8125rem]">
        <p className="font-medium text-brand-navy">
          {alert.subject_name} — {w.kinds[alert.kind]}
          {incident?.key ? ` (${incident.key})` : ""}
        </p>
        <p className="text-xs text-shell-muted">
          {[
            t.environment.twin.certainty[alert.certainty],
            fill(w.since, { ago: ago(t, alert.opened_at) }),
            alert.status === "open" ? fill(w.seen, { ago: ago(t, alert.last_seen_at) }) : null,
            alert.status === "resolved"
              ? fill(w.resolvedBy, {
                  signal: ((alert.resolution?.signal as string[] | undefined) ?? []).join(", ") || "—",
                })
              : alert.status === "closed"
                ? w.closed
                : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>
      {alert.status === "open" ? (
        <Link
          href={intentionHref(words)}
          className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-shell-nav-active hover:underline"
        >
          {w.analyse}
          <ArrowRight className="rtl:-scale-x-100 size-3.5" aria-hidden="true" />
        </Link>
      ) : null}
    </li>
  );
}

/** The alerts the plan includes — or, when it does not, that limit and
 * the plan that lifts it: never an alert simulated, never the states hidden. */
export function AlertsCard({ monitoring }: { monitoring: Monitoring | undefined }) {
  const t = useDictionary();
  const w = t.environment.twin.alerts;
  if (!monitoring) return null;
  const { entitlement } = monitoring;
  const plan = (name: string | null) =>
    name ? name.charAt(0).toUpperCase() + name.slice(1) : "—";
  return (
    <Card
      title={w.title}
      icon={<IconTile icon={Bell} tone="violet" className="size-9" />}
      action={
        entitlement.proactive ? (
          <span className="text-xs text-shell-muted">
            {entitlement.alerts.includes("email") ? w.email : w.inApp}
          </span>
        ) : undefined
      }
    >
      {entitlement.proactive ? (
        <div data-testid="alerts">
          {monitoring.open.length === 0 ? (
            <p className="text-[0.8125rem] text-shell-muted">{w.none}</p>
          ) : (
            <>
              <p className="text-xs text-shell-muted">
                {fill(w.open, { count: monitoring.open.length })}
              </p>
              <ul className="divide-y divide-shell-line/60">
                {monitoring.open.map((alert) => (
                  <AlertRow key={alert.id} alert={alert} />
                ))}
              </ul>
            </>
          )}
          {monitoring.ended.length ? (
            <details className="mt-2 text-[0.8125rem]">
              <summary className="cursor-pointer text-shell-nav-active">
                {fill(w.ended, { count: monitoring.ended.length })}
              </summary>
              <ul className="divide-y divide-shell-line/60">
                {monitoring.ended.map((alert) => (
                  <AlertRow key={alert.id} alert={alert} />
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      ) : (
        <div className="space-y-2 text-[0.8125rem]" data-testid="alerts-limit">
          <p className="font-medium text-brand-navy">{w.limitTitle}</p>
          <p className="text-shell-muted">
            {fill(w.limitBody, {
              plan: plan(entitlement.plan),
              alerts: plan(entitlement.alerts_from),
              email: plan(entitlement.email_from),
            })}
          </p>
          <CardLink href={routes.billing()}>{w.limitAction}</CardLink>
        </div>
      )}
    </Card>
  );
}

/** A thing's state on its sheet: the state, how it is known, when last
 * observed, and each source that shows it in its state. */
export function TwinProvenance({
  twin,
  sources,
}: {
  twin: TwinState | null | undefined;
  sources: readonly TwinSource[];
}) {
  const t = useDictionary();
  const w = t.environment.twin;
  if (!twin) return null;
  return (
    <div className="mt-2 space-y-1 text-xs text-shell-muted" data-testid="twin-provenance">
      <p className="flex flex-wrap items-center gap-2">
        <TwinBadge state={twin.state} size="sm" />
        <span>{twinHow(t, twin)}</span>
        {twin.observed_at ? (
          <span>· {fill(w.observed, { ago: ago(t, twin.observed_at) })}</span>
        ) : null}
      </p>
      {sources.length ? (
        <p>
          {w.coverage.sources} :{" "}
          {sources
            .map((s) => `${s.name} (${w.coverage.states[s.state].toLowerCase()})`)
            .join(", ")}
        </p>
      ) : null}
    </div>
  );
}
