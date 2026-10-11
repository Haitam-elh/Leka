"use client";

import {
  AlertTriangle,
  ArrowRight,
  ChevronRight,
  Gauge,
  History,
  Layers,
  Loader2,
  type LucideIcon,
  Network,
  Puzzle,
  Rocket,
  UsersRound,
} from "lucide-react";
import Link from "next/link";
import { cn } from "cn";

import { IconTile, type TileTone } from "@/components/environment/parts";
import { hoursSince, timeAgo } from "@/components/knowledge/time";
import { usePermissions } from "@/components/shell/shell-provider";
import { routes } from "@/config/routes";
import { typeSegment } from "@/lib/environment";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Finding } from "@/lib/insights";
import { useInsights } from "@/lib/insights-queries";

/** How long, said short: « 45 s », « 2 min 05 s ». */
export function duration(ms: number): string {
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds} s`;
  return `${Math.floor(seconds / 60)} min ${String(seconds % 60).padStart(2, "0")} s`;
}

/** The findings a card names, unless told fewer; the rest are counted. */
const SHOWN = 3;

const TONE: Record<Finding["severity"], TileTone> = {
  high: "danger",
  medium: "warning",
  low: "info",
};

const ICON: Record<string, LucideIcon> = {
  architecture: Network,
  organisation: UsersRound,
  context: Layers,
  change: Rocket,
  gaps: Puzzle,
  quality: Gauge,
  evolution: History,
};

interface Worded {
  title: string;
  detail: string | null;
}

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

/** Whole days since a moment the API gave. */
function days(iso: string): number {
  return Math.max(0, Math.floor(hoursSince(iso) / 24));
}

/** A gap (LEKA-379): what LEKA does not know, or no longer knows — null
 * for a code the interface does not know yet. */
function wordGap(t: Dictionary, finding: Finding, kind: string): Worded | null {
  const p = finding.params;
  const g = t.insights.gap;
  const name = text(p.name);
  const count = Number(p.dependents) || 0;
  const relied = count ? fill(g.relied, { kind, count }) : kind || null;
  if (finding.code.startsWith("gap.coverage.")) {
    const family = text(p.family);
    const title = (g.coverage as Record<string, string>)[family];
    const covers = (g.covers as Record<string, string>)[family];
    return title ? { title, detail: covers ? fill(covers, { count: text(p.count) }) : null } : null;
  }
  switch (finding.code) {
    case "gap.missing_entity.runtime":
      return { title: fill(g.runtime, { name }), detail: relied };
    case "gap.missing_entity.code":
      return { title: fill(g.code, { name }), detail: relied };
    case "gap.missing_entity.data_model":
      return { title: fill(g.dataModel, { name }), detail: relied };
    case "gap.missing_relationship.isolated":
      return { title: fill(g.isolated, { name }), detail: kind || null };
    case "gap.missing_relationship.business":
      return { title: fill(g.business, { name }), detail: relied };
    case "gap.missing_documentation":
      return { title: fill(g.undocumented, { name }), detail: relied };
    case "gap.stale_documentation": {
      const last = p.last_documented_at;
      return {
        title: fill(g.outdated, { name }),
        detail: typeof last === "string" ? fill(g.changed, { days: days(last) }) : relied,
      };
    }
    case "gap.stale_knowledge.dormant":
      return { title: fill(g.dormant, { name }), detail: relied };
    case "gap.stale_source": {
      const since = typeof p.since === "string" ? p.since : null;
      if (p.status === "error") {
        return {
          title: fill(g.sourceFailing, { name }),
          detail: since ? fill(g.lastRead, { days: days(since) }) : g.neverRead,
        };
      }
      return since
        ? { title: fill(g.sourceLate, { name, days: days(since) }), detail: g.mayHaveChanged }
        : { title: fill(g.sourceNever, { name }), detail: null };
    }
    default:
      return null;
  }
}

/** Weak knowledge (LEKA-381): a thing's, with what lowers it most; an
 * area's, with how many things it holds — null for a code not known yet. */
function wordQuality(t: Dictionary, finding: Finding): Worded | null {
  const p = finding.params;
  const q = t.insights.quality;
  const score = Math.round((Number(p.score) || 0) * 100);
  const name = text(p.name);
  if (finding.code === "quality.low") {
    const first = Array.isArray(p.missing) ? text(p.missing[0]) : "";
    const lacks = (q.missing as Record<string, string>)[first];
    const said = fill(q.score, { score });
    return { title: fill(q.low, { name }), detail: lacks ? `${said} · ${lacks}` : said };
  }
  if (finding.code === "quality.low_area") {
    const scope = text(p.scope);
    return {
      title: scope === "workspace" ? q.workspace : fill(q.area, { name }),
      detail: fill(q.areaDetail, {
        scope: (q.scopes as Record<string, string>)[scope] ?? scope,
        count: text(p.entities),
        score,
      }),
    };
  }
  return null;
}

/** What the model's recent course says (LEKA-383), and what to do about
 * it — null for a code the interface does not know yet. */
function wordEvolution(t: Dictionary, finding: Finding): Worded | null {
  const p = finding.params;
  const e = t.insights.evolution;
  const name = text(p.name);
  const listed = (key: string) => {
    const found = p[key];
    return Array.isArray(found) ? found.map(text).filter(Boolean).join(", ") : "";
  };
  const advice = (e.recommendations as Record<string, string>)[text(p.recommendation)];
  const detail = (said: string | null) => [said, advice].filter(Boolean).join(" · ") || null;
  switch (finding.code) {
    case "evolution.dependencies_grew":
      return {
        title: fill(e.dependencies, { name, count: text(p.added) }),
        detail: detail(fill(e.dependenciesDetail, { names: listed("names") })),
      };
    case "evolution.owner_lost":
      return {
        title: fill(e.ownerLost, { name }),
        detail: detail(
          typeof p.at === "string"
            ? fill(e.ownerLostDetail, { names: listed("before"), days: days(p.at) })
            : null,
        ),
      };
    case "evolution.owner_changed":
      return {
        title: fill(e.ownerChanged, { name }),
        detail: detail(
          fill(e.ownerChangedDetail, { before: listed("before"), after: listed("after") }),
        ),
      };
    case "evolution.removed_relied":
      return {
        title: fill(e.removed, { name }),
        detail: detail(fill(e.removedDetail, { names: listed("names") })),
      };
    case "evolution.architecture_moved":
      return {
        title: e.architecture,
        detail: detail(
          fill(e.architectureDetail, { created: text(p.created), removed: text(p.removed) }),
        ),
      };
    case "evolution.incidents_rising":
      return {
        title: fill(e.incidents, { name }),
        detail: detail(
          fill(e.incidentsDetail, { recent: text(p.recent), before: text(p.before) }),
        ),
      };
    case "evolution.volatile":
      return {
        title: fill(e.volatile, { name }),
        detail: detail(fill(e.volatileDetail, { count: text(p.changes) })),
      };
    case "evolution.quality_fell": {
      const percent = (value: unknown) => Math.round((Number(value) || 0) * 100);
      const column = (t.knowledgeQuality.columns as Record<string, string>)[text(p.column)];
      return {
        title:
          p.scope === "workspace"
            ? e.qualityFellWorkspace
            : fill(e.qualityFell, { name: column ?? name }),
        detail: detail(
          fill(e.qualityFellDetail, { before: percent(p.before), after: percent(p.after) }),
        ),
      };
    }
    default:
      return null;
  }
}

/** A finding in the reader's words, from its code and values — its English
 * statement when the interface does not know the code yet. */
export function word(t: Dictionary, finding: Finding): Worded {
  const p = finding.params;
  const w = t.insights;
  const kind = (t.environment.architecture.kinds as Record<string, string>)[text(p.kind)] ?? text(p.kind);
  switch (finding.code) {
    case "dependency.concentration": {
      const state = text(p.status);
      const detail =
        state === "incident"
          ? w.dependency.incident
          : state === "attention"
            ? w.dependency.attention
            : p.deduced === true
              ? w.dependency.deduced
              : p.watched === false
                ? w.dependency.unwatched
                : w.dependency.watched;
      return {
        title: fill(w.dependency.title, { count: text(p.dependents), name: text(p.name) }),
        detail,
      };
    }
    case "ownership.no_owner": {
      const maintainers = Array.isArray(p.maintainers) ? p.maintainers.map(text) : [];
      const count = Number(p.dependents) || 0;
      const detail = maintainers.length
        ? fill(w.ownership.maintained, { names: maintainers.slice(0, 3).join(", ") })
        : count
          ? fill(w.ownership.relied, { kind, count })
          : kind || null;
      return { title: fill(w.ownership.title, { name: text(p.name) }), detail };
    }
    case "context.failed":
      return {
        title: fill(w.context.failed, { title: text(p.title) }),
        detail: fill(w.context.version, { version: text(p.version) }),
      };
    case "context.behind":
      return {
        title: fill(w.context.behind, { title: text(p.title) }),
        detail: fill(w.context.behindDetail, { count: text(p.pending) }),
      };
    case "context.weak":
      return {
        title: fill(w.context.weak, { title: text(p.title) }),
        detail:
          typeof p.score === "number"
            ? fill(w.context.weakDetail, { score: Math.round(p.score * 100) })
            : null,
      };
    case "change.impact": {
      const kinds = w.change.kinds as Record<string, string>;
      const said = { kind: kinds[text(p.kind)] ?? text(p.kind), change: text(p.change) };
      const incidents = Number(p.incidents) || 0;
      const when = fill(w.change.when, { hours: text(p.hours) });
      return {
        title: incidents
          ? fill(w.change.followed, { ...said, count: incidents })
          : fill(w.change.reaches, { ...said, count: text(p.reached) }),
        detail: p.environment ? `${when} · ${text(p.environment)}` : when,
      };
    }
    default:
      return (
        (finding.code.startsWith("gap.") ? wordGap(t, finding, kind) : null) ??
        (finding.code.startsWith("quality.") ? wordQuality(t, finding) : null) ??
        (finding.code.startsWith("evolution.") ? wordEvolution(t, finding) : null) ?? {
          title: finding.statement,
          detail: null,
        }
      );
  }
}

/** Where a finding's subject is shown: an entity's sheet, a source's page
 * — or, for a family of sources not connected, the sources, to connect one.
 * A context has no page of its own. */
export function hrefOf(finding: Finding): string | null {
  const subject = finding.subject;
  // What the model's course says of the whole (LEKA-383): the quality an
  // area lost is the Qualité view's; what the architecture did, Activité's.
  if (finding.code === "evolution.quality_fell" && subject.type !== "entity") {
    return `${routes.environment()}?tab=quality`;
  }
  if (subject.type === "workspace" && finding.category === "evolution") return routes.activity();
  if (subject.type === "coverage") return routes.sources();
  if (subject.type === "source") return subject.id ? routes.source(subject.id) : null;
  if (subject.type !== "entity" || !subject.id || !subject.kind) return null;
  return routes.entity(typeSegment(subject.kind), subject.id);
}

function Line({ finding }: { finding: Finding }) {
  const t = useDictionary();
  const { title, detail } = word(t, finding);
  const href = hrefOf(finding);
  const body = (
    <>
      <IconTile
        icon={ICON[finding.category] ?? AlertTriangle}
        tone={TONE[finding.severity]}
        className="size-9"
      />
      <span className="min-w-0 flex-1">
        <span className="block text-[0.8125rem] leading-snug font-semibold text-brand-navy">
          {title}
        </span>
        <span className="block truncate text-xs text-shell-muted">
          {t.insights.severity[finding.severity]}
          {detail ? ` · ${detail}` : ""}
        </span>
      </span>
      {href ? <ChevronRight className="rtl:-scale-x-100 mt-2 size-4 text-shell-muted" aria-hidden="true" /> : null}
    </>
  );
  return (
    <li data-testid={`finding-${finding.code}`}>
      {href ? (
        <Link
          href={href}
          className="-mx-1.5 flex items-start gap-3 rounded-lg px-1.5 py-2.5 outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        >
          {body}
        </Link>
      ) : (
        <div className="flex items-start gap-3 py-2.5">{body}</div>
      )}
    </li>
  );
}

/**
 * "Insights LEKA" (LEKA-377): what LEKA's analyses concluded and still hold
 * — the most pressing open findings, each worded and leading to what it is
 * about — when the latest analysis ran, and, for who may ask LEKA
 * something, the way to analyse now. Never invented: before any analysis
 * it says so; when nothing is open, that too.
 */
export function LekaInsights({
  className,
  shown = SHOWN,
}: {
  className?: string;
  /** How many findings it names: fewer where its row is short. */
  shown?: number;
}) {
  const t = useDictionary();
  const w = t.insights;
  const permissions = usePermissions();
  const { summary, analyse, waiting, since } = useInsights();
  // How long it has been at it: read again with every poll.
  const took = waiting && since !== null ? Math.max(0, Date.now() - since) : 0;
  const mayAsk = permissions?.includes("intention:create") ?? false;
  const data = summary.data;
  const open = data ? data.open.high + data.open.medium + data.open.low : 0;

  let body: React.ReactNode;
  if (summary.isPending) {
    body = (
      <div className="space-y-2" aria-hidden="true" data-testid="insights-loading">
        <div className="h-12 animate-pulse rounded-lg bg-shell-canvas" />
        <div className="h-12 animate-pulse rounded-lg bg-shell-canvas" />
      </div>
    );
  } else if (summary.isError || !data) {
    body = (
      <p className="text-[0.875rem] text-shell-muted" data-testid="insights-failed">
        {w.failed}{" "}
        <button
          type="button"
          onClick={() => void summary.refetch()}
          className="font-medium text-shell-nav-active underline-offset-2 hover:underline"
        >
          {w.retry}
        </button>
      </p>
    );
  } else if (data.top.length) {
    body = (
      <>
        <ul className="divide-y divide-shell-line/60" data-testid="insights-findings">
          {data.top.slice(0, shown).map((finding) => (
            <Line key={finding.id} finding={finding} />
          ))}
        </ul>
        {open > shown ? (
          <p className="mt-1 text-xs text-shell-muted">{fill(w.more, { count: open - shown })}</p>
        ) : null}
      </>
    );
  } else {
    body = (
      <p className="text-[0.875rem] leading-snug text-shell-muted" data-testid="insights-empty">
        {data.latest ? w.nothing : w.never}
      </p>
    );
  }

  const latest = data?.latest;
  const finished = latest?.finished_at;
  return (
    <div className={cn("flex flex-1 flex-col", className)}>
      <div className="flex-1">{body}</div>
      {finished && !waiting ? (
        <p className="mt-3 text-xs text-shell-muted">
          {fill(w.analysed, { when: timeAgo(t, finished) })}
        </p>
      ) : null}
      {latest && !waiting && (latest.status === "failed" || latest.status === "abandoned") ? (
        <p className="mt-1 text-xs text-state-danger" data-testid="insights-run-failed">
          {w.runFailed}
        </p>
      ) : null}
      {latest && !waiting && latest.status === "partial" ? (
        <p className="mt-1 text-xs text-state-warning" data-testid="insights-run-partial">
          {w.runPartial}
        </p>
      ) : null}
      {waiting && took >= 60_000 ? (
        <p className="mt-2 text-xs text-shell-muted" role="status" data-testid="insights-background">
          {w.background}
        </p>
      ) : null}
      {analyse.data?.queued === false ? (
        <p className="mt-2 text-xs text-shell-muted" role="status">
          {w.already}
        </p>
      ) : null}
      {mayAsk ? (
        <button
          type="button"
          onClick={() => analyse.mutate()}
          disabled={waiting}
          data-testid="insights-analyse"
          className="mt-3 flex items-center justify-center gap-2 rounded-lg bg-brand-navy px-4 py-2.5 text-sm font-medium text-white outline-none hover:bg-brand-navy/90 focus-visible:ring-3 focus-visible:ring-brand-violet/40 disabled:opacity-70"
        >
          {waiting ? (
            <>
              <Loader2 className="size-4 animate-spin" aria-hidden="true" />
              {took >= 10_000 ? fill(w.analysingFor, { took: duration(took) }) : w.analysing}
            </>
          ) : (
            <>
              {w.analyse}
              <ArrowRight className="rtl:-scale-x-100 size-4" aria-hidden="true" />
            </>
          )}
        </button>
      ) : null}
    </div>
  );
}
