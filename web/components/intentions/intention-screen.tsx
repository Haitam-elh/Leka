"use client";

import { Archive, ArchiveRestore, History, Link2, SearchX, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";

import { Card, entityHref } from "@/components/environment/parts";
import { kindOf, StatusPill } from "@/components/intentions/intentions-list";
import { UnderstandingPanel } from "@/components/intentions/understanding";
import { useConfirm } from "@/components/interactions/confirm";
import { Pill } from "@/components/intelligence/pill";
import { exactDate, timeAgo } from "@/components/knowledge/time";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { RouteTabs } from "@/components/shell/route-tabs";
import { useCurrentUser } from "@/components/shell/shell-provider";
import { ErrorState } from "@/components/states/error-state";
import { StatePanel } from "@/components/states/state-panel";
import { Button, buttonVariants } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import type { IntentionDetail, IntentionEvent, IntentionLink } from "@/lib/intentions/api";
import {
  useIntention,
  useIntentionChange,
  useIntentionHistory,
} from "@/lib/intentions/queries";
import { buildBreadcrumb } from "@/lib/navigation/breadcrumb";
import { matchRoute } from "@/lib/navigation/active";
import { useNamePage } from "@/lib/navigation/page-name";
import { notify } from "@/lib/notify";

/**
 * An intention's page (LEKA-384): where it stands, what was asked, what it
 * is linked to, and — tab Historique — everything that happened to it, as
 * its history keeps it (GET /intentions/{id}/history): who, LEKA or a
 * person, when, from where to where, why. The tabs Analyse, Preuves and
 * Actions come with the analysis engine (LEKA-388 to 391) and say so.
 *
 * Its asker, or who may approve, cancels it while it can be, archives it
 * once done with, restores it. Nothing is shown that the API did not say.
 */

type Dictionary = ReturnType<typeof useDictionary>;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function IntentionScreen() {
  const t = useDictionary();
  const params = useParams<{ intentionId: string }>();
  const pathname = usePathname() ?? "/";
  const id = params.intentionId ?? "";
  const valid = UUID.test(id);
  const intention = useIntention(valid ? id : "");
  const data = intention.data;
  const crumbs = buildBreadcrumb(pathname, t, data ? () => data.title : undefined);
  useNamePage(pathname, data?.title);
  const tab = matchRoute(pathname)?.tab ?? "overview";
  const missing =
    !valid || (intention.error instanceof ApiError && intention.error.status === 404);

  let body: React.ReactNode;
  if (missing) {
    body = (
      <StatePanel
        icon={SearchX}
        title={t.intentions.notFound}
        testId="intention-not-found"
        actions={
          <Link href={routes.intentions()} className={buttonVariants({ variant: "outline" })}>
            {t.intentions.title}
          </Link>
        }
      />
    );
  } else if (intention.isError) {
    body = <ErrorState error={intention.error} onRetry={() => void intention.refetch()} />;
  } else if (!data) {
    body = <div className="h-80 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  } else if (tab === "history") {
    body = <HistoryTab id={data.id} />;
  } else if (tab === "overview") {
    body = <Overview intention={data} />;
  } else {
    body = (
      <p className="rounded-xl border border-shell-line bg-white px-5 py-6 text-[0.875rem] text-shell-muted">
        {t.intentions.soon}
      </p>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title={data?.title ?? t.nav.intentionDetail}
        breadcrumb={crumbs}
        actions={data ? <Actions intention={data} /> : undefined}
      />
      {data ? (
        <div className="-mt-3 mb-4 text-[0.875rem] text-shell-accent-muted">
          <Subtitle intention={data} />
        </div>
      ) : null}
      {/* The tabs are the route's: shown whatever the intention, so a shared
          link lands on its tab. */}
      <RouteTabs />
      {body}
    </PageContainer>
  );
}

function Subtitle({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const me = useCurrentUser();
  const when = timeAgo(t, intention.created_at);
  const name = intention.created_by && intention.created_by === me?.id ? t.intentions.you : null;
  return (
    <span className="flex flex-wrap items-center gap-2">
      <StatusPill status={intention.status} />
      {intention.archived_at ? <Pill tone="neutral">{t.intentions.archived}</Pill> : null}
      <span>
        {name ? fill(t.intentions.createdBy, { when, name }) : fill(t.intentions.created, { when })}
      </span>
    </span>
  );
}

function Actions({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const w = t.intentions.actions;
  const confirm = useConfirm();
  const change = useIntentionChange(intention.id);
  const cancellable = intention.moves.includes("cancelled");
  const archivable =
    !intention.archived_at && ["completed", "rejected", "cancelled"].includes(intention.status);

  async function run(kind: "cancel" | "archive" | "restore", reason?: string) {
    try {
      await change.mutateAsync({ change: kind, reason });
      notify.success({ title: w.done });
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : String(error) });
    }
  }

  return (
    <div className="flex flex-wrap gap-2">
      {cancellable ? (
        <Button
          type="button"
          variant="outline"
          disabled={change.isPending}
          data-testid="intention-cancel"
          onClick={async () => {
            const reason = await confirm({
              title: w.cancelTitle,
              description: w.cancelBody,
              confirmLabel: w.cancelConfirm,
              destructive: true,
              reasonLabel: w.cancelReason,
            });
            if (reason !== null) await run("cancel", reason);
          }}
        >
          <XCircle className="size-4" aria-hidden="true" />
          {w.cancel}
        </Button>
      ) : null}
      {archivable ? (
        <Button
          type="button"
          variant="outline"
          disabled={change.isPending}
          data-testid="intention-archive"
          onClick={() => void run("archive")}
        >
          <Archive className="size-4" aria-hidden="true" />
          {w.archive}
        </Button>
      ) : null}
      {intention.archived_at ? (
        <Button
          type="button"
          variant="outline"
          disabled={change.isPending}
          data-testid="intention-restore"
          onClick={() => void run("restore")}
        >
          <ArchiveRestore className="size-4" aria-hidden="true" />
          {w.restore}
        </Button>
      ) : null}
    </div>
  );
}

// ── Vue d'ensemble ──────────────────────────────────────────────────────

function scopeLines(t: Dictionary, locale: string, scope: Record<string, unknown>): string[] {
  const w = t.intentions.overview;
  const lines: string[] = [];
  if (typeof scope.environment === "string") {
    lines.push(`${w.environment} · ${scope.environment}`);
  }
  if (typeof scope.since === "string") {
    const since = exactDate(locale, scope.since);
    const until = typeof scope.until === "string" ? ` → ${exactDate(locale, scope.until)}` : "";
    lines.push(`${w.period} · ${since}${until}`);
  }
  if (Array.isArray(scope.services) && scope.services.length) {
    lines.push(fill(w.services, { count: scope.services.length }));
  }
  if (Array.isArray(scope.sources) && scope.sources.length) {
    lines.push(fill(w.sources, { count: scope.sources.length }));
  }
  return lines;
}

function LinkLine({ link }: { link: IntentionLink }) {
  const t = useDictionary();
  const kind = t.intentions.linkKinds[link.kind];
  const type = typeof link.detail.type === "string" ? link.detail.type : null;
  const version = typeof link.detail.version === "number" ? link.detail.version : null;
  const label =
    link.kind === "context" && version !== null
      ? `${link.label} · v${version}`
      : link.label;
  return (
    <li className="flex items-start gap-2 text-[0.8125rem]" data-testid="intention-link">
      <Pill tone="neutral">{kind}</Pill>
      {link.kind === "entity" && type ? (
        <Link
          href={entityHref({ id: link.ref_id, type })}
          className="min-w-0 font-medium text-brand-navy hover:underline"
        >
          {label}
        </Link>
      ) : (
        <span className="min-w-0 text-brand-navy">{label}</span>
      )}
    </li>
  );
}

function Overview({ intention }: { intention: IntentionDetail }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.intentions.overview;
  const kind = kindOf(t, intention.kind);
  const scope = scopeLines(t, locale, intention.scope as Record<string, unknown>);
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-4">
        {intention.understanding ? (
          <UnderstandingPanel
            understanding={intention.understanding}
            intentionId={intention.status === "needs_clarification" ? intention.id : undefined}
          />
        ) : null}
        <Card title={w.asked}>
          <p className="text-[0.9375rem] text-brand-navy" data-testid="intention-text">
            {intention.text}
          </p>
          <dl className="mt-3 grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] gap-x-3 gap-y-2 text-[0.8125rem]">
            <dt className="text-shell-muted">{w.kind}</dt>
            <dd className="text-brand-navy">{kind ?? "—"}</dd>
            <dt className="text-shell-muted">{w.scope}</dt>
            <dd className="text-brand-navy">
              {scope.length ? scope.map((line) => <span key={line} className="block">{line}</span>) : w.noScope}
            </dd>
          </dl>
        </Card>
        <Card title={w.summary}>
          <p
            className={
              intention.summary
                ? "text-[0.9375rem] text-brand-navy"
                : "text-[0.875rem] text-shell-muted"
            }
          >
            {intention.summary ?? w.noSummary}
          </p>
        </Card>
      </div>
      <div className="flex flex-col gap-4">
        <Card title={w.links} icon={<Link2 className="size-4 text-shell-muted" aria-hidden="true" />}>
          {intention.links.length ? (
            <ul className="space-y-2">
              {intention.links.map((link) => (
                <LinkLine key={link.id} link={link} />
              ))}
            </ul>
          ) : (
            <p className="text-[0.8125rem] text-shell-muted">{w.noLinks}</p>
          )}
        </Card>
        <Card title={w.next}>
          <ul className="flex flex-wrap gap-2" data-testid="intention-moves">
            {intention.moves.length ? (
              intention.moves.map((status) => (
                <li key={status}>
                  <Pill tone="neutral">{t.intentions.statuses[status]}</Pill>
                </li>
              ))
            ) : (
              <li className="text-[0.8125rem] text-shell-muted">—</li>
            )}
          </ul>
        </Card>
      </div>
    </div>
  );
}

// ── Historique ──────────────────────────────────────────────────────────

/** One event of its history, in words. */
export function eventSaid(t: Dictionary, event: IntentionEvent): string {
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

function HistoryTab({ id }: { id: string }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const me = useCurrentUser();
  const w = t.intentions.history;
  const history = useIntentionHistory(id);
  if (history.isError) {
    return <ErrorState error={history.error} onRetry={() => void history.refetch()} />;
  }
  if (!history.data) {
    return <div className="h-64 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  }
  return (
    <Card title={w.title} icon={<History className="size-4 text-shell-muted" aria-hidden="true" />}>
      {history.data.length === 0 ? (
        <p className="text-[0.8125rem] text-shell-muted">{w.empty}</p>
      ) : (
        <ol className="relative space-y-4 border-l border-shell-line pl-5" data-testid="intention-history">
          {history.data.map((event) => {
            const detail = event.detail as Record<string, unknown>;
            const who =
              event.actor === "system"
                ? w.leka
                : event.by && event.by === me?.id
                  ? fill(w.by, { name: t.intentions.you })
                  : w.someone;
            return (
              <li key={event.id} className="relative" data-testid="intention-event" data-kind={event.kind}>
                <span
                  aria-hidden="true"
                  className="absolute top-1.5 -left-[1.6rem] size-2.5 rounded-full border-2 border-white bg-brand-violet"
                />
                <p className="text-[0.875rem] font-medium text-brand-navy">{eventSaid(t, event)}</p>
                <p className="text-xs text-shell-muted">
                  <time dateTime={event.at}>{exactDate(locale, event.at)}</time> · {who}
                  {typeof detail.version === "number"
                    ? ` · ${fill(w.version, { version: detail.version })}`
                    : ""}
                </p>
                {event.reason ? (
                  <p className="mt-0.5 text-xs text-brand-navy">
                    {fill(w.reason, { reason: event.reason })}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}
