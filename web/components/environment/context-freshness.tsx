"use client";

import { CircleAlert, CircleCheck } from "lucide-react";
import { useId, useState } from "react";

import { cn } from "cn";

import { exactDate, timeAgo } from "@/components/knowledge/time";
import { typeLabel } from "@/components/environment/parts";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  type AssembledContext,
  type ContextChange,
  type ContextRead,
  type ContextVersion,
  contexts,
} from "@/lib/context";
import { useContextChecks, useContextMutation } from "@/lib/context-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

/**
 * A context keeping up with the company (LEKA-374), as the Contexte tab
 * says it: up to date with the company model, or behind — since when, on
 * what — whether it follows the model on its own; why each version was
 * made and how it differs from the one before; every time it was made
 * again, and what came of it. Each change in words: what the model changed
 * of what it holds, or what of its request or intention changed. Nothing is
 * drawn that the API did not say.
 */

type Dictionary = ReturnType<typeof useDictionary>;

/** Not used for this long, a context is no longer made again on its own:
 * the API's ACTIVE_DAYS. */
const ACTIVE_DAYS = 14;

/** "il y a 3 min", inside a sentence — timeAgo says it at the start of one. */
function ago(t: Dictionary, iso: string): string {
  const said = timeAgo(t, iso);
  return said.charAt(0).toLocaleLowerCase() + said.slice(1);
}

/** What of an entity changed: its name, its lifecycle, an attribute. */
function fieldName(t: Dictionary, name: string): string {
  const fields = t.environment.sheet.context.fields as Record<string, string>;
  return name.startsWith("attributes.") ? name.slice("attributes.".length) : (fields[name] ?? name);
}

/** A request's or an intention's value, in words. */
function valueSaid(t: Dictionary, locale: string, field: string, value: unknown): string {
  const w = t.environment.sheet.context.change;
  if (value === null || value === undefined || value === "") return "—";
  if ((field === "roots" || field === "sources") && Array.isArray(value)) {
    return fill(w.count, { count: value.length });
  }
  if (field === "kind" && typeof value === "string") {
    return (t.intent.kinds as Record<string, string>)[value] ?? value;
  }
  if (field === "relationships" && Array.isArray(value) && value.length === 0) return w.every;
  if (field === "text" && typeof value === "string") return `« ${value} »`;
  if (field === "until" && typeof value === "string") return exactDate(locale, value);
  if (field === "period" && typeof value === "object") {
    const { since, until } = value as { since?: string; until?: string };
    return since && until ? `${exactDate(locale, since)} – ${exactDate(locale, until)}` : "—";
  }
  if (Array.isArray(value)) return value.length ? value.map(String).join(", ") : "—";
  if (typeof value === "object") return Object.keys(value).length ? JSON.stringify(value) : "—";
  return String(value);
}

/** One change, in words. */
export function changeSaid(t: Dictionary, locale: string, change: ContextChange): string {
  const w = t.environment.sheet.context.change;
  const how = change.change ?? "changed";
  if (change.kind === "entity") {
    const changed = change.fields ?? [];
    const fields = changed.length
      ? ` (${changed.map((name) => fieldName(t, name)).join(", ")})`
      : "";
    const what = change.type ? `${typeLabel(t, change.type)} ` : "";
    return `${what}${change.name ?? ""} — ${w.entity[how]}${fields}${
      change.touches === "words" ? ` · ${w.words}` : ""
    }`;
  }
  if (change.kind === "relationship") {
    const verb =
      (t.knowledge.relationships as Record<string, string>)[change.type ?? ""] ?? change.type;
    const [from, to] = (change.name ?? "").split(" → ");
    return `${from} ${verb} ${to ?? ""} — ${w.relationship[how]}`;
  }
  if (change.kind === "model") return w.model;
  const labels = (change.kind === "request" ? w.request : w.intent) as Record<string, string>;
  const field = change.field ?? "";
  return `${labels[field] ?? field} : ${valueSaid(t, locale, field, change.before)} → ${valueSaid(
    t,
    locale,
    field,
    change.after,
  )}`;
}

/** Up to date with the model, or behind — since when, on what — and
 * whether it is made again on its own. */
export function FreshnessPanel({
  context,
  canMake,
  onUpdate,
  updating,
}: {
  context: ContextRead;
  canMake: boolean;
  onUpdate: () => void;
  updating: boolean;
}) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.environment.sheet.context.freshness;
  const said = context.freshness;
  const [open, setOpen] = useState(false);
  const follow = useContextMutation(contexts.follow);
  const switchId = useId();
  const stale = said.state === "stale";
  const behind = said.reasons.includes("changes");
  const following: Record<ContextRead["freshness"]["following"], string> = {
    active: w.following.active,
    dormant: fill(w.following.dormant, { days: ACTIVE_DAYS }),
    off: w.following.off,
    archived: w.following.archived,
  };

  return (
    <section
      aria-label={stale ? w.staleTitle : w.freshTitle}
      data-testid="context-freshness"
      data-state={said.state}
      className={cn(
        "rounded-lg px-3 py-2 text-[0.8125rem]",
        stale ? "bg-state-warning-soft" : "bg-shell-canvas",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        {stale ? (
          <CircleAlert className="size-4 shrink-0 text-state-warning" aria-hidden="true" />
        ) : (
          <CircleCheck className="size-4 shrink-0 text-state-success" aria-hidden="true" />
        )}
        <p className="font-medium text-brand-navy">
          {!stale
            ? w.upToDate
            : behind && said.since
              ? fill(w.stale, { ago: ago(t, said.since) })
              : w.failed}
        </p>
        {said.checked_at ? (
          <span className="text-shell-muted">
            {fill(w.checked, { ago: ago(t, said.checked_at) })}
          </span>
        ) : null}
        <span className="flex-1" />
        {stale && canMake ? (
          <Button size="sm" onClick={onUpdate} disabled={updating}>
            {w.update}
          </Button>
        ) : null}
      </div>
      {behind && said.changes > 0 ? (
        <div className="mt-1">
          <p className="text-brand-navy">{fill(w.count, { count: said.changes })}</p>
          {said.pending.length > 0 ? (
            <>
              <button
                type="button"
                aria-expanded={open}
                onClick={() => setOpen(!open)}
                className="rounded text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
              >
                {open ? w.hide : fill(w.show, { count: said.pending.length })}
              </button>
              {open ? (
                <ul
                  className="mt-1 max-h-48 space-y-0.5 overflow-y-auto"
                  data-testid="context-pending"
                >
                  {[...said.pending].reverse().map((change, at) => (
                    <li key={`${at}-${change.kind}-${change.ref_id ?? change.name ?? ""}`}>
                      {changeSaid(t, locale, change)}
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          ) : null}
        </div>
      ) : null}
      <div className="mt-1 flex flex-wrap items-center gap-2 text-shell-muted">
        <span data-testid="context-following">{following[said.following]}</span>
        {canMake && said.following !== "archived" ? (
          <span className="ml-auto inline-flex items-center gap-2">
            <Switch
              size="sm"
              checked={context.follow}
              disabled={follow.isPending}
              aria-labelledby={switchId}
              onCheckedChange={(checked) =>
                follow.mutate(
                  { id: context.id, follow: checked },
                  { onError: () => notify.error({ title: w.followFailed }) },
                )
              }
            />
            <span id={switchId} className="text-brand-navy">
              {w.follow}
            </span>
          </span>
        ) : null}
      </div>
    </section>
  );
}

/** Why a version was made, and how it differs from the one before: what
 * of its request or intention changed, how many changes of the model it
 * followed; added, removed, said differently. */
export function VersionWhy({
  version,
}: {
  version: Pick<ContextVersion | AssembledContext, "changes" | "change_count" | "delta">;
}) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.environment.sheet.context.change;
  const asked = (version.changes ?? []).filter((c) => c.kind === "request" || c.kind === "intent");
  const followed = version.change_count - asked.length;
  const parts = [
    ...asked.map((change) => changeSaid(t, locale, change)),
    ...(followed > 0 ? [fill(w.followed, { count: followed })] : []),
  ];
  if (!parts.length && !version.delta) return null;
  return (
    <span className="block text-shell-muted" data-testid="context-version-why">
      {parts.join(" · ")}
      {version.delta ? (
        <span className="tabular-nums">
          {parts.length ? " · " : ""}
          {fill(t.environment.sheet.context.delta, {
            added: version.delta.added,
            removed: version.delta.removed,
            changed: version.delta.changed,
          })}
        </span>
      ) : null}
    </span>
  );
}

/** Every time the context was made again, the latest first: why, by whom,
 * after how many changes, and what came of it. */
export function ChecksPanel({ contextId }: { contextId: string }) {
  const t = useDictionary();
  const w = t.environment.sheet.context.checks;
  const checks = useContextChecks(contextId);
  const rows = checks.data ?? [];
  return (
    <section
      aria-label={w.title}
      className="rounded-lg border border-shell-line p-3 text-xs"
      data-testid="context-checks"
    >
      <h3 className="mb-1 text-[0.8125rem] font-semibold text-brand-navy">{w.title}</h3>
      {rows.length === 0 ? (
        <p className="text-shell-muted">{checks.isPending ? "…" : w.empty}</p>
      ) : (
        <ol className="max-h-48 space-y-1.5 overflow-y-auto">
          {rows.map((row) => (
            <li key={`${row.checked_at}-${row.version}`}>
              <span className="block font-medium text-brand-navy">
                {fill(w.row, { ago: ago(t, row.checked_at), trigger: w.trigger[row.trigger] })}
                {row.checked_by ? "" : ` · ${w.byLeka}`}
              </span>
              <span
                className={cn(
                  "block",
                  row.outcome === "failed" ? "text-state-danger" : "text-shell-muted",
                )}
              >
                {fill(w.outcome[row.outcome], { version: row.version })}
                {row.change_count > 0 ? ` · ${fill(w.after, { count: row.change_count })}` : ""}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
