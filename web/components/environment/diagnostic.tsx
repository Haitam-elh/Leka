"use client";

import { KeyRound, Sparkles } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { Card, entityHref, typeLabel } from "@/components/environment/parts";
import {
  askAbout,
  intentionHref,
  TwinBadge,
  TwinCounts,
} from "@/components/environment/twin";
import { KnowledgeTable, type KnowledgeColumn } from "@/components/knowledge/knowledge-table";
import { timeAgo } from "@/components/knowledge/time";
import { routes } from "@/config/routes";
import type { Environment } from "@/lib/environment";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import {
  type Blocker,
  diagnose,
  type Fix,
  type Tracked,
  TWIN_STATES,
  type TwinSource,
  type TwinStateName,
} from "@/lib/twin";

/**
 * « Mon environnement », diagnosed (LEKA-532): the score made of the things
 * tracked, one by one — never a provider's box — so every figure can be
 * counted again from the rows below it.
 *
 *   - its health (in good health / tracked) apart from its coverage (a
 *     known state / tracked): seen is not well, and 100 % no guarantee;
 *   - what keeps it from 100 %, the most urgent first: each thing, its
 *     source, environment, last observation, why — only what its sources
 *     show — what would fix it, and what it takes off the score;
 *   - the ceiling, when a provider gives no state LEKA can read;
 *   - what AWS refused to let LEKA read, with the permissions to grant;
 *   - the rule, as the code applies it, and each state's meaning.
 *
 * Opened from the overall state's counts, the home's card, or
 * `?state=unknown` — the one list of what « Inconnu » counts.
 */

type Dictionary = ReturnType<typeof useDictionary>;

const percentOf = (locale: string, share: number | null) =>
  share === null
    ? "-"
    : new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(share);

/** Why a thing is in its state, in a sentence: what its sources say. */
export function whyOf(
  t: Dictionary,
  row: Tracked,
  byId: ReadonlyMap<string, TwinSource>,
  sources: readonly TwinSource[],
): string {
  const w = t.environment.twin;
  const twin = row.twin;
  const names = row.sources.map((id) => byId.get(id)?.name).filter(Boolean);
  const monitors = sources
    .filter((s) => s.category === "observability" && s.state !== "disabled")
    .map((s) => s.name);
  const words = (w.why as Record<string, string>)[twin.reason] ?? (w.reasons as Record<string, string>)[twin.reason];
  const said = fill(words ?? twin.reason, {
    sources: names.length ? names.join(", ") : w.why.noSource,
    said: twin.said ?? "",
    type: row.resource_type ?? typeLabel(t, row.entity.type),
    key: twin.incident?.key.includes(":") ? twin.incident.name : (twin.incident?.key ?? ""),
    monitors: monitors.join(", "),
  });
  return twin.was ? `${said} (${fill(w.was, { state: w.states[twin.was].toLowerCase() })})` : said;
}

/** What would lift it, and where: a link when LEKA has the place. */
function FixCell({ blocker, byId }: { blocker: Blocker; byId: ReadonlyMap<string, TwinSource> }) {
  const t = useDictionary();
  const w = t.environment.diagnostic.fixes;
  const { row, fix } = blocker;
  const failing = row.sources.map((id) => byId.get(id)).find((s) => s && s.state !== "read");
  const first = row.sources.map((id) => byId.get(id)).find(Boolean);
  const look = "text-xs font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40";
  const target: Partial<Record<Fix, { href: string; text: string }>> = {
    incident: row.twin.incident
      ? { href: entityHref({ id: row.twin.incident.id, type: "incident" }), text: w.incident }
      : { href: routes.activity(), text: w.incident },
    investigate: { href: intentionHref(askAbout(t, row.entity.name, row.twin.state)), text: w.investigate },
    source: {
      href: failing ? `${routes.sources()}?source=${failing.id}` : routes.sources(),
      text: fill(w.source, { source: failing?.name ?? first?.name ?? "" }),
    },
    monitor: { href: routes.sources(), text: w.monitor },
    watch: { href: routes.sources(), text: w.watch },
    cloud: { href: routes.sources(), text: w.cloud },
    unsure: {
      href: first ? `${routes.sources()}?source=${first.id}` : routes.sources(),
      text: w.unsure,
    },
  };
  const found = target[fix];
  return (
    <span data-testid="diagnostic-fix" data-fix={fix}>
      {found ? (
        <Link href={found.href} className={look}>
          {fix === "investigate" ? <Sparkles className="me-1 inline size-3.5" aria-hidden="true" /> : null}
          {found.text}
        </Link>
      ) : (
        <span className="text-xs text-shell-muted">{w.limit}</span>
      )}
    </span>
  );
}

export function EnvironmentDiagnostic({
  environment,
  filter,
  onFilter,
}: {
  environment: Environment;
  filter: TwinStateName | null;
  onFilter: (state: TwinStateName | null) => void;
}) {
  const t = useDictionary();
  const w = t.environment.diagnostic;
  const { format: locale } = useLocale();
  const tracked = useMemo(() => environment.tracked ?? [], [environment.tracked]);
  const sources = useMemo(() => environment.sources ?? [], [environment.sources]);
  const byId = useMemo(() => new Map(sources.map((s) => [s.id, s])), [sources]);
  const found = useMemo(() => diagnose(tracked), [tracked]);
  const points = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
  const rows = filter ? found.blockers.filter((b) => b.row.twin.state === filter) : found.blockers;
  const capped = found.blockers.filter((b) => b.fix === "limit").length;
  const unread = sources.filter((s) => (s.unread ?? []).length > 0);
  const lastRead = environment.freshness?.last_read_at ?? null;
  // The counts as the rows count them: the same figures, one source.
  const states = useMemo(() => {
    const counted: Record<string, number> = Object.fromEntries(TWIN_STATES.map((s) => [s, 0]));
    for (const row of tracked) counted[row.twin.state] += 1;
    return counted;
  }, [tracked]);

  const columns: KnowledgeColumn<Blocker>[] = [
    {
      id: "name",
      header: w.columns.name,
      sortValue: (b) => b.row.entity.name,
      cell: ({ row }) => (
        <span className="flex min-w-0 flex-col gap-1">
          <Link
            href={entityHref(row.entity)}
            className="font-medium text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          >
            {row.entity.name}
          </Link>
          <span data-testid="diagnostic-state" data-state={row.twin.state}>
            <TwinBadge state={row.twin.state} size="sm" />
          </span>
        </span>
      ),
    },
    {
      id: "type",
      header: w.columns.type,
      sortValue: (b) => b.row.entity.type,
      cell: ({ row }) => (
        <span className="flex flex-col text-xs">
          <span>{typeLabel(t, row.entity.type)}</span>
          {row.resource_type ? (
            <span className="font-mono text-[0.6875rem] text-shell-muted">{row.resource_type}</span>
          ) : null}
        </span>
      ),
    },
    {
      id: "source",
      header: w.columns.source,
      cell: ({ row }) => {
        const names = row.sources.map((id) => byId.get(id)?.name).filter(Boolean);
        return (
          <span className="text-xs" data-testid="diagnostic-source">
            {names.length ? names.join(", ") : t.environment.twin.why.noSource}
          </span>
        );
      },
    },
    {
      id: "environment",
      header: w.columns.environment,
      sortValue: (b) => b.row.environment ?? "",
      cell: ({ row }) => (
        <span className="text-xs">
          {[row.environment, row.region].filter(Boolean).join(" · ") || (
            <span className="text-shell-muted">{w.unsaid}</span>
          )}
        </span>
      ),
    },
    {
      id: "observed",
      header: w.columns.observed,
      sortValue: (b) => b.row.twin.observed_at ?? "",
      cell: ({ row }) =>
        row.twin.observed_at ? (
          <time className="text-xs" dateTime={row.twin.observed_at}>
            {timeAgo(t, row.twin.observed_at)}
          </time>
        ) : (
          <span className="text-xs text-shell-muted">{t.environment.twin.list.never}</span>
        ),
    },
    {
      id: "why",
      header: w.columns.why,
      // Sentences: they wrap, the table scrolls in its frame on a phone.
      className: "min-w-[16rem] whitespace-normal",
      cell: ({ row }) => (
        <span className="block max-w-[22rem] text-xs text-brand-navy" data-testid="diagnostic-why">
          {whyOf(t, row, byId, sources)}
        </span>
      ),
    },
    {
      id: "fix",
      header: w.columns.fix,
      className: "min-w-[12rem] whitespace-normal",
      cell: (blocker) => (
        <span className="block max-w-[16rem]">
          <FixCell blocker={blocker} byId={byId} />
        </span>
      ),
    },
    {
      id: "points",
      header: w.columns.points,
      align: "end",
      cell: (b) => (
        <span
          className="text-xs font-semibold tabular-nums text-brand-navy"
          title={fill(w.pointsTitle, { total: found.total })}
          data-testid="diagnostic-points"
        >
          {fill(w.points, { points: points.format(b.points) })}
        </span>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-4" data-testid="diagnostic" id="diagnostic">
      <Card title={w.title}>
        <p className="-mt-1 mb-3 text-[0.8125rem] text-shell-muted">{w.lead}</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-lg border border-shell-line px-3 py-2.5" data-testid="diagnostic-health">
            <p className="text-xs text-shell-muted">{w.health}</p>
            <p className="text-[1.5rem] font-bold tabular-nums text-brand-navy">
              {percentOf(locale, found.health)}
            </p>
            <p className="text-xs text-shell-muted">
              {fill(w.healthSaid, { healthy: found.healthy, total: found.total })}
            </p>
          </div>
          <div className="rounded-lg border border-shell-line px-3 py-2.5" data-testid="diagnostic-coverage">
            <p className="text-xs text-shell-muted">{w.coverage}</p>
            <p className="text-[1.5rem] font-bold tabular-nums text-brand-navy">
              {percentOf(locale, found.coverage)}
            </p>
            <p className="text-xs text-shell-muted">
              {fill(w.coverageSaid, { known: found.known, total: found.total })}
            </p>
          </div>
        </div>
        <p className="mt-3 text-[0.8125rem] text-brand-navy">{w.apart}</p>
        {found.total ? (
          <p className="mt-2 text-[0.8125rem] font-medium text-brand-navy" data-testid="diagnostic-reachable">
            {found.reachable !== null
              ? fill(w.reachable, { percent: percentOf(locale, found.reachable), count: capped })
              : w.reachableAll}
          </p>
        ) : null}
      </Card>

      <Card title={w.blockers}>
        <div className="mb-3 flex flex-col gap-2">
          <TwinCounts states={states} active={filter} onPick={onFilter} />
          {filter ? (
            <p className="text-[0.8125rem] text-shell-muted" data-testid="diagnostic-filter">
              <span className="font-medium text-brand-navy">
                {fill(w.only, { state: t.environment.twin.states[filter], count: rows.length })}
              </span>{" "}
              {t.environment.twin.definitions[filter]}{" "}
              <button
                type="button"
                onClick={() => onFilter(null)}
                className="font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
              >
                {w.all}
              </button>
            </p>
          ) : null}
        </div>
        <KnowledgeTable
          caption={w.blockers}
          columns={columns}
          rows={rows}
          rowKey={(b) => b.row.entity.id}
          empty={{
            title: filter ? fill(w.noneIn, { state: t.environment.twin.states[filter] }) : w.none,
          }}
        />
      </Card>

      {unread.length ? (
        <Card title={w.unread.title}>
          <ul className="flex flex-col gap-2.5" data-testid="diagnostic-unread">
            {unread.map((source) => (
              <li key={source.id} className="flex items-start gap-2.5 text-[0.8125rem]">
                <KeyRound className="mt-0.5 size-4 shrink-0 text-state-warning" aria-hidden="true" />
                <span className="min-w-0 flex-1">
                  <span className="block text-brand-navy">
                    {fill(w.unread.body, {
                      source: source.name,
                      what: (source.unread ?? [])
                        .map((c) => (w.unread.what as Record<string, string>)[c] ?? c)
                        .join(", "),
                    })}
                  </span>
                  <span className="mt-0.5 block text-xs text-shell-muted">
                    {fill(w.unread.grant, { needs: "" })}
                    {(source.needs ?? []).map((need, i) => (
                      <code key={need} className="font-mono text-[0.6875rem] text-brand-navy">
                        {i ? ", " : ""}
                        {need}
                      </code>
                    ))}
                  </span>
                  <Link
                    href={`${routes.sources()}?source=${source.id}`}
                    className="mt-1 inline-block text-xs font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
                  >
                    {w.unread.open}
                  </Link>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <Card title={w.method.title}>
        <div className="space-y-1.5 text-[0.8125rem] text-brand-navy" data-testid="diagnostic-method">
          <p className="font-medium">
            {fill(w.method.formula, {
              healthy: found.healthy,
              total: found.total,
              percent: percentOf(locale, found.health),
            })}
          </p>
          <p>{w.method.counted}</p>
          <p>{w.method.excluded}</p>
          <p>{w.method.notHealthy}</p>
          <p>{w.method.deduced}</p>
          <p className="text-shell-muted">
            {lastRead ? fill(w.method.at, { ago: timeAgo(t, lastRead).toLowerCase() }) : w.method.never}
          </p>
        </div>
        <details className="mt-3 rounded-lg bg-shell-canvas px-3 py-2 text-[0.8125rem]" data-testid="diagnostic-states">
          <summary className="cursor-pointer font-medium text-brand-navy">{w.states}</summary>
          <dl className="mt-2 space-y-1.5">
            {TWIN_STATES.map((state) => (
              <div key={state} data-state={state}>
                <dt className="font-medium text-brand-navy">{t.environment.twin.states[state]}</dt>
                <dd className="text-shell-muted">{t.environment.twin.definitions[state]}</dd>
              </div>
            ))}
          </dl>
        </details>
      </Card>
    </div>
  );
}
