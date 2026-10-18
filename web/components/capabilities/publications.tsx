"use client";

import { useQueryClient } from "@tanstack/react-query";
import { BookOpen, Check, CircleAlert, ExternalLink, ListChecks, Loader2, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { cn } from "cn";

import type { TileTone } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { usePermissions } from "@/components/shell/shell-provider";
import { Button } from "@/components/ui/button";
import { Markdown } from "@/components/ui/markdown";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { SPINNING } from "@/lib/motion";
import { notify } from "@/lib/notify";
import type { Publication, PublicationItem, PublicationKind } from "@/lib/publications";
import { publicationKeys, usePublicationActions, useRunPublications } from "@/lib/publications-queries";
import type { Source } from "@/lib/sources";
import { useAllowWrite, useSources } from "@/lib/sources-queries";

/**
 * What LEKA proposes to send out of a deliverable (2026-10-18): tickets for
 * a Jira project, pages for a Confluence space.
 *
 *     asked      the source and the project or space chosen — LEKA drafts,
 *                from what the agent delivered, in a minute
 *     proposed   each ticket or page, to keep or leave, read in full —
 *                « Ajouter à Jira (N) », « Publier sur Confluence (N) »
 *     sent       each with its key or its page, or why not
 *
 * Nothing reaches Jira or Confluence before a person accepted it, and then
 * only new issues and new pages, on a source whose admin allowed it.
 */

const TONE: Record<Publication["status"], TileTone> = {
  drafting: "info",
  proposed: "warning",
  applied: "success",
  partly: "warning",
  rejected: "neutral",
  failed: "danger",
};

const SOURCE_TYPE = { issues: "jira", pages: "confluence" } as const;
const SCOPE = { issues: "projects", pages: "spaces" } as const;
const CONNECTED: readonly Source["status"][] = ["active", "degraded"];

const FIELD = "h-8 rounded-md border border-shell-line bg-white px-2 text-[0.8125rem] text-brand-navy";

/** Why the API refused: the code it said, read in the person's words. */
function why(error: unknown, errors: Record<string, string>, fallback: string): string {
  if (!(error instanceof ApiError)) return fallback;
  const code = Object.values(error.fieldErrors ?? {})[0];
  return (code && errors[code]) || error.message || fallback;
}

/** The project's keys, or the space's, the source reads — none when it
 * reads them all. */
function scopeOf(source: Source | undefined, kind: PublicationKind): string[] {
  const listed = source?.config[SCOPE[kind]];
  return Array.isArray(listed) ? listed.map(String) : [];
}

export function RunPublications({ runId }: { runId: string }) {
  const t = useDictionary();
  const w = t.publications;
  const { data } = useRunPublications(runId);
  const [asking, setAsking] = useState<PublicationKind | null>(null);
  return (
    <section
      className="flex flex-col gap-3 rounded-xl border border-shell-line bg-white px-5 py-4"
      aria-labelledby="publications-title"
      data-testid="publications"
    >
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1">
          <h3 id="publications-title" className="text-[0.9375rem] font-semibold text-brand-navy">
            {w.title}
          </h3>
          <p className="text-[0.8125rem] text-shell-muted">{w.intro}</p>
        </div>
        {(["issues", "pages"] as const).map((kind) => (
          <Button
            key={kind}
            type="button"
            size="sm"
            variant={asking === kind ? "default" : "outline"}
            aria-expanded={asking === kind}
            onClick={() => setAsking(asking === kind ? null : kind)}
            data-testid={`publication-ask-${kind}`}
          >
            {kind === "issues" ? (
              <ListChecks className="size-3.5" aria-hidden="true" />
            ) : (
              <BookOpen className="size-3.5" aria-hidden="true" />
            )}
            {w.ask[kind]}
          </Button>
        ))}
      </div>
      {asking ? <AskForm key={asking} runId={runId} kind={asking} onDone={() => setAsking(null)} /> : null}
      {data?.length ? (
        <ul className="flex flex-col gap-3" data-testid="publication-list">
          {data.map((publication) => (
            <PublicationCard key={publication.id} runId={runId} publication={publication} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function AskForm({ runId, kind, onDone }: { runId: string; kind: PublicationKind; onDone: () => void }) {
  const t = useDictionary();
  const w = t.publications;
  const sources = useSources();
  const { ask } = usePublicationActions(runId);
  const usable = (sources.data ?? []).filter(
    (source) => source.type === SOURCE_TYPE[kind] && CONNECTED.includes(source.status),
  );
  const [sourceId, setSourceId] = useState<string | null>(null);
  const source = usable.find((each) => each.id === sourceId) ?? usable[0];
  const listed = scopeOf(source, kind);
  const [typed, setTyped] = useState("");
  const target = (listed.length ? listed.find((key) => key === typed) ?? listed[0] : typed).trim();

  if (sources.isLoading) {
    return <div className="h-16 animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />;
  }
  if (!source) {
    return (
      <p className="rounded-lg bg-shell-canvas px-3 py-2.5 text-[0.8125rem] text-brand-navy" data-testid="publication-no-source">
        {w.noSource[kind]}{" "}
        <Link href={routes.sources()} className="font-medium text-shell-nav-active underline">
          {w.connect}
        </Link>
      </p>
    );
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!source || !target) return;
    try {
      await ask.mutateAsync({ kind, source_id: source.id, target });
      onDone();
    } catch (error) {
      notify.error({ title: why(error, w.errors as Record<string, string>, w.failed) });
    }
  }

  const allowed = Boolean(source.config[kind]);
  return (
    <form
      className="flex flex-col gap-3 rounded-lg border border-shell-line bg-shell-canvas/50 p-3"
      onSubmit={(event) => void submit(event)}
      data-testid="publication-form"
      data-kind={kind}
    >
      <div className="flex flex-wrap items-end gap-3">
        {usable.length > 1 ? (
          <label className="flex flex-col gap-1 text-xs text-shell-muted">
            {w.source}
            <select className={FIELD} value={source.id} onChange={(e) => setSourceId(e.target.value)}>
              {usable.map((each) => (
                <option key={each.id} value={each.id}>
                  {each.display_name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <p className="flex flex-col gap-1 text-xs text-shell-muted">
            {w.source}
            <span className="flex h-8 items-center text-[0.8125rem] font-medium text-brand-navy">{source.display_name}</span>
          </p>
        )}
        <label className="flex flex-col gap-1 text-xs text-shell-muted">
          {w.target[kind]}
          {listed.length ? (
            <select
              className={cn(FIELD, "font-mono")}
              value={target}
              onChange={(e) => setTyped(e.target.value)}
              data-testid="publication-target"
            >
              {listed.map((key) => (
                <option key={key} value={key}>
                  {key}
                </option>
              ))}
            </select>
          ) : (
            <input
              className={cn(FIELD, "w-36 font-mono")}
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={w.placeholder[kind]}
              maxLength={255}
              required
              data-testid="publication-target"
            />
          )}
        </label>
        <Button type="submit" size="sm" disabled={ask.isPending || !target} data-testid="publication-draft">
          {ask.isPending ? <Loader2 className={cn("size-3.5", SPINNING)} aria-hidden="true" /> : null}
          {w.draft[kind]}
        </Button>
      </div>
      <p className="text-xs text-shell-muted">{w.draftHint[kind]}</p>
      {!allowed ? (
        <p className="text-xs text-state-warning" data-testid="publication-form-not-allowed">
          {w.notYetAllowed[kind]}
        </p>
      ) : null}
    </form>
  );
}

function PublicationCard({ runId, publication }: { runId: string; publication: Publication }) {
  const t = useDictionary();
  const w = t.publications;
  const errors = w.errors as Record<string, string>;
  const { accept, reject } = usePublicationActions(runId);
  // Anyone who may ask drafts; who may approve sends, or rejects; who
  // manages the sources allows LEKA to write there, in one click.
  const permissions = usePermissions();
  const approver = permissions?.includes("intention:approve") ?? false;
  const manager = permissions?.includes("source:manage") ?? false;
  const allow = useAllowWrite();
  const client = useQueryClient();
  const kind = publication.kind;
  // What is left out, not what is chosen: every item is chosen by default,
  // those drafted after this card was first drawn too.
  const [left, setLeft] = useState<ReadonlySet<string>>(() => new Set());
  const busy = accept.isPending || reject.isPending;
  const proposed = publication.status === "proposed";
  const decided = publication.status === "applied" || publication.status === "partly";
  const picked = publication.items.filter((item) => !left.has(item.id));

  function toggle(id: string) {
    setLeft((was) => {
      const next = new Set(was);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function send() {
    try {
      const done = await accept.mutateAsync({ id: publication.id, items: picked.map((item) => item.id) });
      const sent = done.items.filter((item) => item.url).length;
      notify.success({ title: fill(w.sentDone[kind], { count: sent }) });
    } catch (error) {
      notify.error({ title: why(error, errors, w.failed) });
    }
  }

  async function allowWrites() {
    try {
      await allow.mutateAsync({ sourceId: publication.source_id, flag: kind });
      await client.invalidateQueries({ queryKey: publicationKeys.all });
      notify.success({ title: w.allowedDone[kind] });
    } catch (error) {
      notify.error({ title: why(error, errors, w.failed) });
    }
  }

  async function refuse() {
    try {
      await reject.mutateAsync({ id: publication.id });
      notify.success({ title: w.rejectedDone });
    } catch (error) {
      notify.error({ title: why(error, errors, w.failed) });
    }
  }

  return (
    <li
      className="flex flex-col gap-3 rounded-lg border border-shell-line p-3"
      data-testid="publication"
      data-kind={kind}
      data-status={publication.status}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone={TONE[publication.status]}>{w.statuses[publication.status]}</Pill>
        <span className="text-xs font-medium text-shell-muted">
          {fill(w.where[kind], { target: publication.target })}
        </span>
        {publication.title ? (
          <span className="w-full text-[0.875rem] font-semibold text-brand-navy" dir="auto">
            {publication.title}
          </span>
        ) : null}
      </div>

      {publication.status === "drafting" ? (
        <p className="flex items-center gap-2 text-[0.8125rem] text-shell-muted" role="status">
          <Loader2 className={cn("size-4", SPINNING)} aria-hidden="true" />
          {w.drafting[kind]}
        </p>
      ) : null}
      {publication.status === "failed" ? (
        <p className="text-[0.8125rem] text-state-danger" role="alert" data-testid="publication-failed">
          {errors[publication.error ?? ""] ?? publication.error_detail ?? w.failed}
        </p>
      ) : null}
      {publication.summary ? (
        <p className="text-[0.8125rem] whitespace-pre-wrap text-brand-navy" dir="auto">
          {publication.summary}
        </p>
      ) : null}

      {publication.items.length ? (
        <>
          {proposed ? (
            <div className="flex flex-wrap items-center gap-2 text-xs text-shell-muted">
              <span>{fill(w.chosen, { count: picked.length, total: publication.items.length })}</span>
              <button
                type="button"
                className="font-medium text-shell-nav-active hover:underline"
                onClick={() =>
                  setLeft(
                    picked.length === publication.items.length
                      ? new Set(publication.items.map((item) => item.id))
                      : new Set(),
                  )
                }
              >
                {picked.length === publication.items.length ? w.none : w.all}
              </button>
            </div>
          ) : null}
          <ul className="flex flex-col gap-2">
            {publication.items.map((item) => (
              <ItemRow
                key={item.id}
                kind={kind}
                item={item}
                choosing={proposed}
                chosen={!left.has(item.id)}
                decided={decided}
                onToggle={() => toggle(item.id)}
              />
            ))}
          </ul>
        </>
      ) : null}

      {proposed ? (
        <div className="flex flex-col gap-2">
          {publication.error ? (
            // Refused whole the last time: nothing was sent, it can be sent again.
            <p className="flex items-start gap-1.5 text-xs text-state-danger" role="alert" data-testid="publication-error">
              <CircleAlert className="mt-px size-3.5 shrink-0" aria-hidden="true" />
              {errors[publication.error] ?? publication.error_detail ?? publication.error}
            </p>
          ) : null}
          {!approver ? (
            <p className="text-xs text-shell-muted" data-testid="publication-approvers">
              {w.approvers}
            </p>
          ) : null}
          {!publication.allowed ? (
            <div className="flex flex-wrap items-center gap-2" data-testid="publication-not-allowed">
              <p className="min-w-0 flex-1 text-xs text-state-warning">
                {manager ? w.notAllowedAdmin[kind] : w.notAllowed[kind]}{" "}
                <Link href={routes.source(publication.source_id)} className="font-medium underline">
                  {w.openSource}
                </Link>
              </p>
              {manager ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={allow.isPending}
                  onClick={() => void allowWrites()}
                  data-testid="publication-allow"
                >
                  {allow.isPending ? <Loader2 className={cn("size-3.5", SPINNING)} aria-hidden="true" /> : null}
                  {w.allow[kind]}
                </Button>
              ) : null}
            </div>
          ) : null}
          <p className="text-xs text-shell-muted">{fill(w.sendHint[kind], { target: publication.target })}</p>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              disabled={busy || !approver || !publication.allowed || !picked.length}
              onClick={() => void send()}
              data-testid="publication-send"
            >
              {accept.isPending ? (
                <Loader2 className={cn("size-3.5", SPINNING)} aria-hidden="true" />
              ) : (
                <Check className="size-3.5" aria-hidden="true" />
              )}
              {fill(w.send[kind], { count: picked.length })}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy || !approver}
              onClick={() => void refuse()}
              data-testid="publication-reject"
            >
              <X className="size-3.5" aria-hidden="true" />
              {w.reject}
            </Button>
          </div>
        </div>
      ) : null}
      {decided ? (
        <p className="text-xs text-shell-muted" data-testid="publication-sent">
          {fill(w.sent[kind], {
            count: publication.items.filter((item) => item.url).length,
            total: publication.items.length,
          })}
        </p>
      ) : null}
      {publication.status === "rejected" && publication.note ? (
        <p className="text-xs text-shell-muted">{fill(w.rejectedBecause, { note: publication.note })}</p>
      ) : null}
    </li>
  );
}

function ItemRow({
  kind,
  item,
  choosing,
  chosen,
  decided,
  onToggle,
}: {
  kind: PublicationKind;
  item: PublicationItem;
  choosing: boolean;
  chosen: boolean;
  decided: boolean;
  onToggle: () => void;
}) {
  const t = useDictionary();
  const w = t.publications;
  const errors = w.errors as Record<string, string>;
  const kinds = w.kinds as Record<string, string>;
  const priorities = w.priorities as Record<string, string>;
  return (
    <li
      className={cn(
        "flex gap-2.5 rounded-md border border-shell-line px-3 py-2",
        choosing && !chosen && "bg-shell-canvas/60",
      )}
      data-testid="publication-item"
      data-sent={item.url ? "true" : undefined}
    >
      {choosing ? (
        <input
          type="checkbox"
          className="mt-0.5 size-4 shrink-0 accent-[var(--brand-violet)]"
          checked={chosen}
          onChange={onToggle}
          aria-label={item.title}
        />
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className={cn("text-[0.8125rem] font-medium", chosen || !choosing ? "text-brand-navy" : "text-shell-muted")} dir="auto">
            {item.title}
          </span>
          {kind === "issues" && item.kind ? <Pill tone="neutral">{kinds[item.kind] ?? item.kind}</Pill> : null}
          {kind === "issues" && item.priority ? (
            <Pill tone={item.priority === "highest" || item.priority === "high" ? "danger" : "neutral"}>
              {priorities[item.priority] ?? item.priority}
            </Pill>
          ) : null}
          {item.labels?.length ? (
            <span className="font-mono text-[0.6875rem] text-shell-muted">{item.labels.join(" · ")}</span>
          ) : null}
        </div>
        {item.url ? (
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex w-fit items-center gap-1 text-[0.8125rem] font-medium text-shell-nav-active hover:underline"
            data-testid="publication-link"
          >
            <ExternalLink className="size-3.5" aria-hidden="true" />
            {kind === "issues" && item.key ? fill(w.openIssue, { key: item.key }) : w.openPage}
          </a>
        ) : item.error ? (
          <span className="text-xs text-state-danger" data-testid="publication-item-error">
            {errors[item.error] ?? item.error}
          </span>
        ) : decided ? (
          <span className="text-xs text-shell-muted">{w.notSent}</span>
        ) : null}
        <details className="group">
          <summary className="w-fit cursor-pointer text-xs text-shell-muted hover:text-brand-navy">{w.read[kind]}</summary>
          <div className="mt-2 rounded-md bg-shell-canvas/50 px-3 py-2">
            <Markdown source={item.body} className="text-[0.8125rem]" />
          </div>
        </details>
      </div>
    </li>
  );
}
