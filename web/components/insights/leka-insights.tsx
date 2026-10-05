"use client";

import {
  AlertTriangle,
  ArrowRight,
  ChevronRight,
  Layers,
  Loader2,
  type LucideIcon,
  Network,
  Rocket,
  UsersRound,
} from "lucide-react";
import Link from "next/link";
import { cn } from "cn";

import { IconTile, type TileTone } from "@/components/environment/parts";
import { timeAgo } from "@/components/knowledge/time";
import { usePermissions } from "@/components/shell/shell-provider";
import { routes } from "@/config/routes";
import { typeSegment } from "@/lib/environment";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { Finding } from "@/lib/insights";
import { useInsights } from "@/lib/insights-queries";

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
};

interface Worded {
  title: string;
  detail: string | null;
}

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
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
      return { title: finding.statement, detail: null };
  }
}

/** Where a finding's subject is shown: an entity's sheet. A context has no
 * page of its own. */
function hrefOf(finding: Finding): string | null {
  const subject = finding.subject;
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
      {href ? <ChevronRight className="mt-2 size-4 text-shell-muted" aria-hidden="true" /> : null}
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
  const { summary, analyse, waiting } = useInsights();
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

  const finished = data?.latest?.finished_at;
  return (
    <div className={cn("flex flex-1 flex-col", className)}>
      <div className="flex-1">{body}</div>
      {finished && !waiting ? (
        <p className="mt-3 text-xs text-shell-muted">
          {fill(w.analysed, { when: timeAgo(t, finished) })}
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
              {w.analysing}
            </>
          ) : (
            <>
              {w.analyse}
              <ArrowRight className="size-4" aria-hidden="true" />
            </>
          )}
        </button>
      ) : null}
    </div>
  );
}
