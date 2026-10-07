"use client";

import {
  CalendarClock,
  History,
  Link2,
  Link2Off,
  RefreshCw,
  RotateCcw,
  Undo2,
  X,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { cn } from "cn";

import {
  Card,
  entityHref,
  IconTile,
  typeIcon,
  typeLabel,
} from "@/components/environment/parts";
import { exactDate } from "@/components/knowledge/time";
import { useCurrentUser, usePermissions } from "@/components/shell/shell-provider";
import { ErrorState } from "@/components/states/error-state";
import {
  type EntityAt,
  type EntityChange,
  fieldName,
  type Operation,
} from "@/lib/evolution";
import { useEntityAt, useEntityHistory, useOperations } from "@/lib/evolution-queries";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

/**
 * A thing's Historique (LEKA-383): every version the model recorded,
 * against the one before — what changed, from what, to what — its
 * relationships that came and went, what it was at a moment, and the
 * restores asked: put a version back, take it back. Real history only:
 * the model's own (GET /knowledge/entities/{id}/history).
 */

const CHANGE_TONE: Record<EntityChange["change"], string> = {
  created: "bg-brand-violet-soft text-shell-nav-active",
  changed: "bg-state-info-soft text-state-info",
  removed: "bg-state-danger-soft text-state-danger",
  returned: "bg-state-success-soft text-state-success",
};

const STATUS_TONE: Record<Operation["status"], string> = {
  queued: "bg-state-warning-soft text-state-warning",
  applied: "bg-state-success-soft text-state-success",
  done: "bg-state-success-soft text-state-success",
  failed: "bg-state-danger-soft text-state-danger",
  undone: "bg-shell-canvas text-shell-muted",
};

/** A value as the reader reads it: "—" for none, JSON for what is not
 * text. */
export function shown(value: unknown, nothing = "—"): string {
  if (value === null || value === undefined || value === "") return nothing;
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  const said = JSON.stringify(value);
  return said.length > 80 ? `${said.slice(0, 77)}…` : said;
}

function fieldLabel(t: Dictionary, field: string): string {
  const named = (t.environment.sheet.history.fields as Record<string, string>)[field];
  return named ?? fieldName(field);
}

export function EntityHistory({ entityId, name }: { entityId: string; name: string }) {
  const t = useDictionary();
  const w = t.environment.sheet.history;
  const { locale } = useLocale();
  const history = useEntityHistory(entityId);
  const [moment, setMoment] = useState<string | null>(null);

  if (history.isError) {
    return <ErrorState error={history.error} onRetry={() => void history.refetch()} />;
  }
  const data = history.data;
  if (!data) {
    return <div className="h-64 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  }
  const removed = data.entity.lifecycle === "removed";

  return (
    <div className="flex flex-col gap-4" data-testid="entity-history">
      {moment ? (
        <AtPanel
          entityId={entityId}
          name={name}
          moment={moment}
          onClose={() => setMoment(null)}
        />
      ) : null}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <Card
          title={w.versions}
          icon={<History className="size-5 text-shell-muted" aria-hidden="true" />}
        >
          {data.versions.length ? (
            <ol className="relative space-y-4 border-l border-shell-line pl-5">
              {data.versions.map((version, index) => (
                <Version
                  key={version.id}
                  entityId={entityId}
                  version={version}
                  current={index === 0}
                  restorable={!removed && index > 0}
                  onAt={() => setMoment(version.recorded_at)}
                />
              ))}
            </ol>
          ) : (
            <p className="text-sm text-shell-muted">{w.empty}</p>
          )}
        </Card>
        <div className="flex min-w-0 flex-col gap-4">
          <Card title={w.relations}>
            {data.relationships.length ? (
              <ul className="space-y-2.5" data-testid="history-relationships">
                {data.relationships.map((change) => {
                  const Icon =
                    change.change === "removed"
                      ? Link2Off
                      : change.change === "added"
                        ? Link2
                        : RefreshCw;
                  const verb =
                    (t.knowledge.relationships as Record<string, string>)[change.type] ?? change.type;
                  return (
                    <li key={change.id} className="flex items-start gap-2.5 text-[0.8125rem]">
                      <Icon
                        className={cn(
                          "mt-0.5 size-4 shrink-0",
                          change.change === "removed" ? "text-state-danger" : "text-state-success",
                        )}
                        aria-hidden="true"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="text-brand-navy">
                          <End entity={change.from_entity} /> {verb}{" "}
                          <End entity={change.to_entity} />
                        </span>
                        <span className="block text-xs text-shell-muted">
                          {w.relationChanges[change.change]} ·{" "}
                          {exactDate(locale, change.recorded_at)}
                        </span>
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="text-sm text-shell-muted">{w.relationsEmpty}</p>
            )}
            {data.horizon ? (
              <p className="mt-3 text-xs text-shell-muted">
                {fill(w.horizon, { date: exactDate(locale, data.horizon) })}
              </p>
            ) : null}
          </Card>
          <Card title={w.operations}>
            {data.operations.length ? (
              <ul className="space-y-3" data-testid="history-operations">
                {data.operations.map((operation) => (
                  <OperationLine key={operation.id} operation={operation} />
                ))}
              </ul>
            ) : (
              <p className="text-sm text-shell-muted">{w.operationsEmpty}</p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function End({ entity }: { entity: EntityChange["entity"] }) {
  if (!entity) return <span>—</span>;
  return (
    <Link
      href={entityHref(entity)}
      className="font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
    >
      {entity.name}
    </Link>
  );
}

function Version({
  entityId,
  version,
  current,
  restorable,
  onAt,
}: {
  entityId: string;
  version: EntityChange;
  current: boolean;
  restorable: boolean;
  onAt: () => void;
}) {
  const t = useDictionary();
  const w = t.environment.sheet.history;
  const { locale } = useLocale();
  const permissions = usePermissions();
  const mayDecide = permissions?.includes("intention:approve") ?? false;
  const { restore } = useOperations();
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");

  function confirm() {
    restore.mutate(
      { id: entityId, version: version.version, reason },
      {
        onSuccess: () => {
          setAsking(false);
          setReason("");
          notify.success({ title: w.restored });
        },
        onError: () => notify.error({ title: w.restoreFailed }),
      },
    );
  }

  return (
    <li className="relative" data-testid={`history-version-${version.version}`}>
      <span
        className="absolute top-1.5 -left-[1.6875rem] size-3 rounded-full border-2 border-white bg-brand-violet"
        aria-hidden="true"
      />
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[0.875rem] font-semibold text-brand-navy">
          {fill(w.version, { version: version.version })}
        </span>
        <span className={cn("rounded-md px-2 py-0.5 text-xs font-medium", CHANGE_TONE[version.change])}>
          {w.changes[version.change]}
        </span>
        {current ? (
          <span className="rounded-md border border-shell-line px-2 py-0.5 text-xs text-brand-navy">
            {w.current}
          </span>
        ) : null}
        <span className="text-xs text-shell-muted">{exactDate(locale, version.recorded_at)}</span>
      </div>
      {version.fields.length ? (
        <dl className="mt-1.5 space-y-1 text-[0.8125rem]">
          {version.fields.map((field) => (
            <div key={field.field} className="flex flex-wrap gap-x-2">
              <dt className="text-shell-muted">{fieldLabel(t, field.field)}</dt>
              <dd className="text-brand-navy">
                <span className="text-shell-muted line-through">{shown(field.before, w.nothing)}</span>
                {" → "}
                <span className="font-medium">{shown(field.after, w.nothing)}</span>
              </dd>
            </div>
          ))}
        </dl>
      ) : version.change === "created" ? (
        <p className="mt-1 text-[0.8125rem] text-shell-muted">{w.createdDetail}</p>
      ) : null}
      <div className="mt-2 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={onAt}
          className="flex items-center gap-1.5 rounded text-xs font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        >
          <CalendarClock className="size-3.5" aria-hidden="true" />
          {w.at}
        </button>
        {restorable && mayDecide && !asking ? (
          <button
            type="button"
            onClick={() => setAsking(true)}
            className="flex items-center gap-1.5 rounded text-xs font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          >
            <RotateCcw className="size-3.5" aria-hidden="true" />
            {w.restore}
          </button>
        ) : null}
      </div>
      {asking ? (
        <div
          className="mt-2 rounded-lg border border-shell-line bg-shell-canvas p-3"
          role="group"
          aria-label={fill(w.restoreTitle, { version: version.version })}
        >
          <p className="text-[0.8125rem] font-semibold text-brand-navy">
            {fill(w.restoreTitle, { version: version.version })}
          </p>
          <p className="mt-1 text-xs text-shell-muted">{w.restoreBody}</p>
          <label className="mt-2 block text-xs text-shell-muted">
            {w.reason}
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={500}
              className="mt-1 block w-full rounded-md border border-shell-line bg-white px-2 py-1.5 text-[0.8125rem] text-brand-navy outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40"
            />
          </label>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              onClick={confirm}
              disabled={restore.isPending}
              className="rounded-lg bg-brand-navy px-3 py-1.5 text-xs font-medium text-white outline-none hover:bg-brand-navy/90 focus-visible:ring-3 focus-visible:ring-brand-violet/40 disabled:opacity-70"
            >
              {w.confirm}
            </button>
            <button
              type="button"
              onClick={() => setAsking(false)}
              className="rounded-lg border border-shell-line bg-white px-3 py-1.5 text-xs font-medium text-brand-navy outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-brand-violet/40"
            >
              {w.cancel}
            </button>
          </div>
        </div>
      ) : null}
    </li>
  );
}

function OperationLine({ operation }: { operation: Operation }) {
  const t = useDictionary();
  const w = t.environment.sheet.history;
  const { locale } = useLocale();
  const user = useCurrentUser();
  const permissions = usePermissions();
  const { undo } = useOperations();
  const attributes = (operation.detail.attributes ?? {}) as Record<
    string,
    { before?: unknown; after?: unknown }
  >;
  const title =
    operation.kind === "restore"
      ? fill(w.operation.restore, { version: operation.version ?? "" })
      : w.operation.rebuild;
  return (
    <li className="text-[0.8125rem]" data-testid={`history-operation-${operation.status}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-brand-navy">{title}</span>
        <span className={cn("rounded-md px-2 py-0.5 text-xs font-medium", STATUS_TONE[operation.status])}>
          {w.statuses[operation.status]}
        </span>
      </div>
      <p className="text-xs text-shell-muted">
        {[
          exactDate(locale, operation.created_at),
          user && operation.requested_by === user.id ? w.byYou : null,
          operation.reason,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
      {Object.entries(attributes).map(([name, values]) => (
        <p key={name} className="text-xs text-brand-navy">
          <span className="text-shell-muted">{fieldName(name)} </span>
          {fill(w.restoring, { from: shown(values.before, w.nothing), to: shown(values.after, w.nothing) })}
        </p>
      ))}
      {operation.status === "applied" && permissions?.includes("intention:approve") ? (
        <button
          type="button"
          onClick={() =>
            undo.mutate(
              { id: operation.id },
              {
                onSuccess: () => notify.success({ title: w.undone }),
                onError: () => notify.error({ title: w.undoFailed }),
              },
            )
          }
          disabled={undo.isPending}
          className="mt-1 flex items-center gap-1.5 rounded text-xs font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40 disabled:opacity-70"
        >
          <Undo2 className="size-3.5" aria-hidden="true" />
          {w.undo}
        </button>
      ) : null}
    </li>
  );
}

function AtPanel({
  entityId,
  name,
  moment,
  onClose,
}: {
  entityId: string;
  name: string;
  moment: string;
  onClose: () => void;
}) {
  const t = useDictionary();
  const w = t.environment.sheet.history;
  const { locale } = useLocale();
  const at = useEntityAt(entityId, moment);
  // Opened from a version far down the list: the reader is taken to it.
  const heading = useRef<HTMLDivElement>(null);
  useEffect(() => heading.current?.focus(), [moment]);
  const data: EntityAt | undefined = at.data;
  const attributes = (data?.content?.attributes ?? {}) as Record<string, unknown>;
  return (
    <Card
      title={fill(w.atTitle, { name, date: exactDate(locale, moment) })}
      icon={<CalendarClock className="size-5 text-shell-muted" aria-hidden="true" />}
      action={
        <button
          type="button"
          onClick={onClose}
          aria-label={w.close}
          className="flex size-8 items-center justify-center rounded-lg text-shell-muted outline-none hover:bg-shell-canvas focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      }
    >
      <div data-testid="history-at" ref={heading} tabIndex={-1} className="outline-none">
        {at.isError ? (
          <ErrorState error={at.error} onRetry={() => void at.refetch()} />
        ) : !data ? (
          <div className="h-24 animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />
        ) : !data.existed ? (
          <p className="text-sm text-shell-muted">{fill(w.atMissing, { name })}</p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <h3 className="mb-1.5 text-[0.8125rem] font-semibold text-brand-navy">{w.attributes}</h3>
              {Object.keys(attributes).length ? (
                <dl className="space-y-1 text-[0.8125rem]">
                  {Object.entries(attributes).map(([key, value]) => (
                    <div key={key} className="flex gap-2">
                      <dt className="text-shell-muted">{key}</dt>
                      <dd className="min-w-0 truncate text-brand-navy">{shown(value, w.nothing)}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="text-sm text-shell-muted">{w.noAttributes}</p>
              )}
            </div>
            <div>
              <h3 className="mb-1.5 text-[0.8125rem] font-semibold text-brand-navy">{w.relationsThen}</h3>
              {data.relationships.length ? (
                <ul className="space-y-1 text-[0.8125rem]">
                  {data.relationships.map((tie) => {
                    const verb =
                      (t.knowledge.relationships as Record<string, string>)[tie.type] ?? tie.type;
                    const other = tie.other?.name ?? "—";
                    return (
                      <li key={`${tie.type}-${tie.direction}-${tie.other?.id ?? other}`} className="text-brand-navy">
                        {tie.direction === "outgoing" ? `${name} ${verb} ${other}` : `${other} ${verb} ${name}`}
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="text-sm text-shell-muted">{w.noRelations}</p>
              )}
              {!data.complete ? <p className="mt-2 text-xs text-state-warning">{w.atPartial}</p> : null}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

/**
 * A thing no source shows any more (LEKA-383): gone from the sheets the
 * sources fill, kept by the model — its course is what remains to read.
 * What a link to it opens; `fallback` when the model never knew it.
 */
export function RemovedEntity({
  entityId,
  fallback,
}: {
  entityId: string;
  fallback: React.ReactNode;
}) {
  const t = useDictionary();
  const w = t.environment.sheet.history;
  const { locale } = useLocale();
  const history = useEntityHistory(entityId);
  if (history.isError) return <>{fallback}</>;
  const data = history.data;
  if (!data) {
    return <div className="h-96 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  }
  const removal = data.versions.find((version) => version.change === "removed");
  return (
    <>
      <div className="mb-5 flex items-start gap-4">
        <IconTile icon={typeIcon(data.entity.type)} tone="neutral" className="size-16 rounded-xl [&>svg]:size-8" />
        <div className="min-w-0">
          <h1 className="truncate text-[2rem] leading-tight font-bold tracking-[-0.02em] text-brand-navy">
            {data.entity.name}
          </h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-[0.875rem] text-shell-muted">
            <span>{typeLabel(t, data.entity.type)}</span>
            <span className="rounded-md bg-state-danger-soft px-2 py-0.5 text-xs font-medium text-state-danger">
              {w.changes.removed}
            </span>
          </div>
          <p className="mt-2 max-w-2xl text-[0.875rem] text-shell-nav-active">
            {removal
              ? fill(w.removedSince, { date: exactDate(locale, removal.recorded_at) })
              : w.removedKept}
          </p>
        </div>
      </div>
      <EntityHistory entityId={entityId} name={data.entity.name} />
    </>
  );
}
