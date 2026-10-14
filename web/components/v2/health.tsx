"use client";

import { ArrowRight, ChevronDown } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { cn } from "cn";
import { entityHref } from "@/components/environment/parts";
import { twinHow } from "@/components/environment/twin";
import { timeAgo } from "@/components/knowledge/time";
import { SourceLogo } from "@/components/sources/source-logo";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { routes } from "@/config/routes";
import type { Environment } from "@/lib/environment";
import { useEnvironment } from "@/lib/environment-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import type { SourceKind } from "@/lib/sources";
import { byState, TROUBLE } from "@/lib/twin";

/** The environment's health in one word (2026-10-14, the product call:
 * « point vert : Environnement stable ; orange : Attention requise ; rouge :
 * Incident »). What says it is the twin LEKA keeps — never a figure drawn
 * here. */
export type Health = "loading" | "none" | "stable" | "attention" | "incident";

/** A source that needs a look: failing, degraded, or late. */
const SOURCE_TROUBLE = new Set(["error", "degraded", "stale"]);

export function healthOf(environment: Environment | undefined): Health {
  if (!environment) return "loading";
  const sources = environment.sources ?? [];
  if (sources.length === 0) return "none";
  const states = environment.states ?? {};
  if (environment.incidents_open > 0 || (states.unavailable ?? 0) > 0) return "incident";
  if (
    (states.degraded ?? 0) > 0 ||
    environment.freshness?.late ||
    sources.some((source) => SOURCE_TROUBLE.has(source.state))
  ) {
    return "attention";
  }
  return "stable";
}

const DOT: Record<Health, string> = {
  loading: "bg-shell-line",
  none: "bg-shell-muted",
  stable: "bg-[#16a34a]",
  attention: "bg-[#f59e0b]",
  incident: "bg-[#dc2626]",
};

/** Top right: the dot and its word; opened, the environment as monitoring
 * read now and then — its sources, each one's state, what is wrong and how
 * it is known — not a page of the menu. */
export function HealthDot() {
  const t = useDictionary();
  const w = t.v2.health;
  const environment = useEnvironment();
  const health = healthOf(environment.data);
  const word = health === "loading" ? w.loading : w[health];
  return (
    <Popover>
      <PopoverTrigger
        className="flex items-center gap-2 rounded-full border border-shell-line bg-white px-3 py-1.5 text-[0.8125rem] font-medium text-brand-navy outline-none hover:bg-brand-violet-soft/50 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        aria-label={fill(w.label, { state: word })}
        data-testid="v2-health"
        data-health={health}
      >
        <span className={cn("size-2.5 rounded-full", DOT[health])} aria-hidden="true" />
        <span className="hidden sm:inline">{word}</span>
        <ChevronDown className="size-3.5 text-shell-muted" aria-hidden="true" />
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[22rem] max-w-[calc(100vw-2rem)] p-0">
        <EnvironmentPanel environment={environment.data} health={health} />
      </PopoverContent>
    </Popover>
  );
}

function EnvironmentPanel({
  environment,
  health,
}: {
  environment: Environment | undefined;
  health: Health;
}) {
  const t = useDictionary();
  const w = t.v2.health;
  const sources = environment?.sources ?? [];
  const trouble = byState(environment?.nodes ?? []).filter(
    (node) => node.twin && TROUBLE.has(node.twin.state),
  );
  return (
    <div className="flex max-h-[70vh] flex-col" data-testid="v2-environment">
      <div className="border-b border-shell-line px-4 py-3">
        <p className="text-[0.9375rem] font-semibold text-brand-navy">{w.title}</p>
        <p className="flex items-center gap-2 text-[0.8125rem] text-shell-muted">
          <span className={cn("size-2 rounded-full", DOT[health])} aria-hidden="true" />
          {health === "loading" ? w.loading : w[health]}
          {environment && environment.incidents_open > 0
            ? ` · ${fill(w.incidents, { count: environment.incidents_open })}`
            : null}
        </p>
        {environment?.freshness?.late ? (
          <p className="mt-1 text-xs text-state-warning">{w.late}</p>
        ) : null}
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
        <section>
          <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-shell-muted uppercase">
            {w.sources} · {fill(w.count, { count: sources.length })}
          </h3>
          <ul className="space-y-1" data-testid="v2-environment-sources">
            {sources.map((source) => (
              <SourceLine key={source.id} source={source} />
            ))}
          </ul>
        </section>
        <section>
          <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-shell-muted uppercase">
            {w.trouble}
          </h3>
          {trouble.length ? (
            <ul className="space-y-1" data-testid="v2-environment-trouble">
              {trouble.slice(0, 6).map((node) => (
                <TroubleLine key={node.id} node={node} />
              ))}
            </ul>
          ) : (
            <p className="text-[0.8125rem] text-shell-muted">{w.troubleNone}</p>
          )}
        </section>
      </div>
      <div className="flex flex-wrap justify-between gap-2 border-t border-shell-line px-4 py-3 text-[0.8125rem]">
        <Link href={routes.sources()} className="font-medium text-brand-violet hover:underline">
          {w.manage}
        </Link>
        <Link
          href={routes.environment()}
          className="inline-flex items-center gap-1 font-medium text-brand-violet hover:underline"
        >
          {w.environment}
          <ArrowRight className="size-3.5 rtl:-scale-x-100" aria-hidden="true" />
        </Link>
      </div>
    </div>
  );
}

type TwinSource = NonNullable<Environment["sources"]>[number];

function SourceLine({ source }: { source: TwinSource }) {
  const t = useDictionary();
  const w = t.v2.health;
  const [open, setOpen] = useState(false);
  const troubled = SOURCE_TROUBLE.has(source.state);
  const said = (w.states as Record<string, string>)[source.state] ?? source.state;
  return (
    <li data-testid="v2-environment-source" data-state={source.state}>
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-start text-[0.8125rem] outline-none hover:bg-shell-canvas focus-visible:ring-2 focus-visible:ring-brand-violet/40"
      >
        <SourceLogo kind={source.kind as SourceKind} className="size-4 shrink-0" />
        <span className="min-w-0 flex-1 truncate text-brand-navy">{source.name}</span>
        <span className={cn("text-xs", troubled ? "text-state-warning" : "text-shell-muted")}>
          {said}
        </span>
      </button>
      {open ? (
        <p className="ps-8 pb-1 text-xs text-shell-muted">
          {source.error ??
            (source.last_synced_at ? timeAgo(t, source.last_synced_at) : said)}
        </p>
      ) : null}
    </li>
  );
}

type TwinNode = Environment["nodes"][number];

function TroubleLine({ node }: { node: TwinNode }) {
  const t = useDictionary();
  const [open, setOpen] = useState(false);
  if (!node.twin) return null;
  const href = node.entity_id ? entityHref({ id: node.entity_id, type: node.type }) : null;
  return (
    <li data-testid="v2-environment-problem">
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-start text-[0.8125rem] outline-none hover:bg-shell-canvas focus-visible:ring-2 focus-visible:ring-brand-violet/40"
      >
        <span
          className={cn(
            "size-2 shrink-0 rounded-full",
            node.twin.state === "unavailable" ? DOT.incident : DOT.attention,
          )}
          aria-hidden="true"
        />
        <span className="min-w-0 flex-1 truncate text-brand-navy">{node.name}</span>
        <span className="text-xs text-shell-muted">
          {(t.environment.twin.states as Record<string, string>)[node.twin.state] ?? node.twin.state}
        </span>
      </button>
      {open ? (
        <div className="space-y-1 ps-6 pb-1 text-xs text-shell-muted">
          <p>{twinHow(t, node.twin)}</p>
          {href ? (
            <Link href={href} className="font-medium text-brand-violet hover:underline">
              {t.v2.health.environment}
            </Link>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}
