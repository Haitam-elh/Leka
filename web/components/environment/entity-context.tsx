"use client";

import {
  Archive,
  ArrowRight,
  ChevronDown,
  Layers,
  Maximize2,
  Minimize2,
  RefreshCw,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";

import { cn } from "cn";

import { exactDate, timeAgo } from "@/components/knowledge/time";
import {
  ChecksPanel,
  changeSaid,
  FreshnessPanel,
  VersionWhy,
} from "@/components/environment/context-freshness";
import { ElementInspect } from "@/components/environment/context-inspect";
import { ElementFeedback, QualityPanel } from "@/components/environment/context-quality";
import {
  ConflictsPanel,
  LeftOutPanel,
  RankWhy,
  RowMarks,
} from "@/components/environment/context-ranking";
import { Card, entityHref, Logo, typeIcon, typeLabel } from "@/components/environment/parts";
import {
  ConfidenceBadge,
  ContextUsedPanel,
  ContextVersionLine,
  retrieverName,
} from "@/components/intelligence";
import { useCurrentUser, usePermissions } from "@/components/shell/shell-provider";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError } from "@/lib/api";
import {
  type AssembledContext,
  type ContextDiff,
  type ContextElement,
  type ContextRead,
  BUDGET,
  contexts,
  type ContextVersion,
  DEPTHS,
  MIN_RELEVANCE,
  type RetrievalMatch,
  WINDOWS,
} from "@/lib/context";
import {
  useAssembledContext,
  useContextDiff,
  useContextEvents,
  useContextMutation,
  useContextVersions,
  useEntityContexts,
} from "@/lib/context-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

/**
 * The "Contexte" tab of an entity's sheet (LEKA-370): what LEKA assembles
 * around this entity to understand a request, read back from the API as it
 * was made. Each element says where it came from — its sources, the key or
 * the record, stated or inferred by which rule, how sure — and why it is
 * there; each version is kept, and two can be compared. How each was
 * ranked, what its sources disagree on and what was left out, and why
 * (LEKA-372), are context-ranking.tsx's; whether it is up to date with the
 * model, why each version was made and every time it was made again
 * (LEKA-374), context-freshness.tsx's — widened or narrowed here; how good
 * it is, and what people say of an element or of what is missing
 * (LEKA-375), context-quality.tsx's; an element inspected — its history,
 * the records it was read from — context-inspect.tsx's (LEKA-376). What
 * happens to the context is heard as it happens: LEKA making it again says
 * so. Archiving it, or changing how it follows the model, is its maker's
 * or an admin's. Nothing is drawn that the API did not say.
 */

type Dictionary = ReturnType<typeof useDictionary>;

/** "il y a 3 min", inside a sentence — timeAgo says it at the start of one. */
function ago(t: Dictionary, iso: string): string {
  const said = timeAgo(t, iso);
  return said.charAt(0).toLocaleLowerCase() + said.slice(1);
}

export function EntityContext({ entityId, entityName }: { entityId: string; entityName: string }) {
  const t = useDictionary();
  const w = t.environment.sheet.context;
  const listed = useEntityContexts(entityId);
  const [chosen, setChosen] = useState<string | null>(null);
  const [making, setMaking] = useState(false);
  const canMake = usePermissions()?.includes("intention:create") ?? false;
  const all = listed.data ?? [];
  const context = all.find((one) => one.id === chosen) ?? all[0] ?? null;

  if (listed.isError) {
    return <ErrorState error={listed.error} onRetry={() => void listed.refetch()} />;
  }
  return (
    <Card
      title={w.title}
      icon={<Layers className="size-5 text-shell-nav-active" aria-hidden="true" />}
      action={
        canMake && context && !making ? (
          <Button variant="outline" size="sm" onClick={() => setMaking(true)}>
            {w.another}
          </Button>
        ) : null
      }
    >
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.intro}</p>
      {listed.isPending ? (
        <div className="h-64 animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />
      ) : making || !context ? (
        <Assemble
          entityId={entityId}
          entityName={entityName}
          canMake={canMake}
          empty={!context}
          onDone={(id) => {
            setMaking(false);
            if (id) setChosen(id);
          }}
        />
      ) : (
        <Shown context={context} all={all} canMake={canMake} onPick={setChosen} />
      )}
    </Card>
  );
}

function Assemble({
  entityId,
  entityName,
  canMake,
  empty,
  onDone,
}: {
  entityId: string;
  entityName: string;
  canMake: boolean;
  empty: boolean;
  onDone: (id: string | null) => void;
}) {
  const t = useDictionary();
  const w = t.environment.sheet.context;
  const [purpose, setPurpose] = useState("");
  const [depth, setDepth] = useState<string>("1");
  const [window, setWindow] = useState<string>("14");
  const create = useContextMutation(contexts.create);
  const depths = DEPTHS.map((value) => ({
    value: String(value),
    label: (w.depths as Record<string, string>)[String(value)],
  }));
  const windows = WINDOWS.map((value) => ({
    value: String(value),
    label: fill(w.windowDays, { days: value }),
  }));

  function submit(event: React.FormEvent) {
    event.preventDefault();
    create.mutate(
      {
        title: entityName,
        purpose: purpose.trim(),
        subject: { type: "entity", id: entityId },
        roots: [entityId],
        depth: Number(depth),
        limit: BUDGET,
        window_days: Number(window),
        strategy: "hybrid",
        min_relevance: MIN_RELEVANCE,
      },
      {
        onSuccess: (made) => {
          notify.success({ title: fill(w.created, { count: made.elements.length }) });
          onDone(made.context_id);
        },
        onError: (error) =>
          notify.error({
            title:
              error instanceof ApiError && error.status === 404 ? w.notInModel : w.failedAction,
          }),
      },
    );
  }

  return (
    <div className="rounded-lg border border-dashed border-shell-line p-4">
      {empty ? (
        <>
          <p className="font-medium text-brand-navy">{w.emptyTitle}</p>
          <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.emptyBody}</p>
        </>
      ) : null}
      {canMake ? (
        <form className="flex flex-wrap items-end gap-3" onSubmit={submit}>
          <label className="flex min-w-64 flex-1 flex-col gap-1 text-[0.8125rem] font-medium text-brand-navy">
            {w.purpose}
            <Input
              value={purpose}
              maxLength={2000}
              placeholder={fill(w.purposeHint, { name: entityName })}
              onChange={(event) => setPurpose(event.target.value)}
            />
          </label>
          <Select
            value={depth}
            onValueChange={(value) => setDepth((value as string | null) ?? "1")}
            items={depths}
          >
            <SelectTrigger className="min-w-36" aria-label={w.depth}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {depths.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select
            value={window}
            onValueChange={(value) => setWindow((value as string | null) ?? "14")}
            items={windows}
          >
            <SelectTrigger className="min-w-44" aria-label={w.window}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {windows.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? w.assembling : w.assemble}
          </Button>
          {!empty ? (
            <Button type="button" variant="ghost" onClick={() => onDone(null)}>
              {w.cancel}
            </Button>
          ) : null}
        </form>
      ) : (
        <p className="text-[0.8125rem] text-shell-muted">{w.readOnly}</p>
      )}
    </div>
  );
}

function Shown({
  context,
  all,
  canMake,
  onPick,
}: {
  context: ContextRead;
  all: readonly ContextRead[];
  canMake: boolean;
  onPick: (id: string) => void;
}) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.environment.sheet.context;
  const [version, setVersion] = useState<number | null>(null);
  const [pair, setPair] = useState<readonly [number, number] | null>(null);
  const versions = useContextVersions(context.id);
  const assembled = useAssembledContext(context.id, version);
  const diff = useContextDiff(context.id, pair);
  const refresh = useContextMutation(contexts.refresh);
  const archive = useContextMutation(contexts.archive);
  const expand = useContextMutation(contexts.expand);
  const compress = useContextMutation(contexts.compress);
  const me = useCurrentUser();
  const permissions = usePermissions();
  // Archiving, or stopping it following the model: its maker's, or an
  // admin's (LEKA-376).
  const canManage =
    canMake &&
    (context.created_by === me?.id || (permissions?.includes("context:manage") ?? false));
  const updated = useCallback(
    (check: { version: number }) =>
      notify.info({ title: fill(w.live.updated, { version: check.version }) }),
    [w],
  );
  useContextEvents(context.id, updated);
  const archived = context.status === "archived";
  const picks = all.map((one) => ({
    value: one.id,
    label: `${one.purpose || one.title} · ${ago(t, one.created_at)}`,
  }));

  function reassemble() {
    refresh.mutate(context.id, {
      onSuccess: (outcome) => {
        const made = outcome.version;
        setVersion(null);
        setPair(null);
        if (made.status === "failed") {
          notify.error({
            title: fill(w.outcome.failed, { version: made.version, error: made.error ?? "" }),
          });
        } else {
          notify.success({
            title: fill(outcome.changed ? w.outcome.changed : w.outcome.unchanged, {
              version: made.version,
            }),
          });
        }
      },
      onError: () => notify.error({ title: w.failedAction }),
    });
  }

  /** Widened one step, or narrowed to half its budget (LEKA-374). */
  function reshape(way: "expand" | "compress") {
    const run = way === "expand" ? expand : compress;
    run.mutate(
      { id: context.id },
      {
        onSuccess: (outcome) => {
          setVersion(null);
          setPair(null);
          const what = (outcome.version.changes ?? [])
            .filter((change) => change.kind === "request")
            .map((change) => changeSaid(t, locale, change))
            .join(", ");
          notify.success({
            title: fill(way === "expand" ? w.reshaped.expanded : w.reshaped.compressed, {
              version: outcome.version.version,
              what,
            }),
          });
        },
        onError: (error) =>
          notify.error({
            title:
              error instanceof ApiError && error.status === 422
                ? way === "expand"
                  ? w.reshaped.refusedExpand
                  : w.reshaped.refusedCompress
                : w.failedAction,
          }),
      },
    );
  }

  return (
    <div className="space-y-3" data-testid="entity-context">
      <div className="flex flex-wrap items-center gap-2">
        {all.length > 1 ? (
          <Select
            value={context.id}
            onValueChange={(value) => {
              if (value) onPick(value as string);
              setVersion(null);
              setPair(null);
            }}
            items={picks}
          >
            <SelectTrigger className="max-w-sm min-w-56" aria-label={w.pick}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {picks.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <p className="font-medium text-brand-navy">{context.purpose || context.title}</p>
        )}
        <Status status={context.status} />
        {assembled.data ? <ContextVersionLine assembled={assembled.data} /> : null}
        <span className="flex-1" />
        {canMake && !archived ? (
          <>
            <Button size="sm" onClick={reassemble} disabled={refresh.isPending}>
              <RefreshCw className={cn("size-3.5", refresh.isPending && "animate-spin")} />
              {w.refresh}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => reshape("expand")}
              disabled={expand.isPending}
            >
              <Maximize2 className="size-3.5" aria-hidden="true" />
              {w.expand}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => reshape("compress")}
              disabled={compress.isPending}
            >
              <Minimize2 className="size-3.5" aria-hidden="true" />
              {w.compress}
            </Button>
            {canManage ? (
              <Button
                size="sm"
                variant="outline"
                disabled={archive.isPending}
                onClick={() =>
                  archive.mutate(context.id, {
                    onSuccess: () => notify.success({ title: w.archived }),
                    onError: () => notify.error({ title: w.archiveFailed }),
                  })
                }
              >
                {w.archive}
              </Button>
            ) : null}
          </>
        ) : null}
      </div>
      {archived ? (
        <p
          className="flex items-center gap-2 rounded-lg bg-state-info-soft px-3 py-2 text-[0.8125rem] text-brand-navy"
          data-testid="context-archived"
        >
          <Archive className="size-4 shrink-0 text-state-info" aria-hidden="true" />
          {w.archivedNote}
        </p>
      ) : (
        <FreshnessPanel
          context={context}
          canMake={canMake}
          canFollow={canManage}
          onUpdate={reassemble}
          updating={refresh.isPending}
        />
      )}
      {assembled.isError ? (
        <ErrorState error={assembled.error} onRetry={() => void assembled.refetch()} />
      ) : assembled.data ? (
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_18rem]">
          <div className="min-w-0 space-y-3">
            <ContextUsedPanel assembled={assembled.data} />
            <Elements assembled={assembled.data} canMake={canMake} />
          </div>
          <div className="space-y-3">
            <QualityPanel assembled={assembled.data} canMake={canMake} />
            <Versions
              rows={versions.data ?? []}
              shown={assembled.data.version}
              onShow={(n) => {
                setVersion(n);
                setPair(null);
              }}
              onCompare={setPair}
            />
            {pair && diff.data ? <Diff diff={diff.data} /> : null}
            <ChecksPanel contextId={context.id} />
            <ConflictsPanel assembled={assembled.data} />
            <LeftOutPanel assembled={assembled.data} />
          </div>
        </div>
      ) : (
        <div className="h-64 animate-pulse rounded-lg bg-shell-canvas" aria-hidden="true" />
      )}
    </div>
  );
}

function Status({ status }: { status: ContextRead["status"] }) {
  const t = useDictionary();
  const tones: Record<ContextRead["status"], string> = {
    assembling: "bg-shell-canvas text-shell-muted",
    assembled: "bg-state-success-soft text-state-success",
    failed: "bg-state-danger-soft text-state-danger",
    archived: "bg-shell-canvas text-shell-muted",
  };
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", tones[status])}>
      {t.environment.sheet.context.status[status]}
    </span>
  );
}

function Elements({ assembled, canMake }: { assembled: AssembledContext; canMake: boolean }) {
  const t = useDictionary();
  const w = t.environment.sheet.context;
  const [open, setOpen] = useState<string | null>(null);
  const names = useMemo(
    () => new Map(assembled.elements.map((element) => [element.ref_id, element])),
    [assembled.elements],
  );
  if (assembled.status === "failed") {
    return (
      <p className="rounded-lg bg-state-danger-soft px-3 py-2 text-[0.8125rem] text-state-danger">
        {fill(w.failedVersion, { error: assembled.error ?? "" })}
      </p>
    );
  }
  return (
    <section aria-label={fill(w.elements, { count: assembled.elements.length })}>
      <h3 className="mb-1 text-[0.8125rem] font-semibold text-brand-navy">
        {fill(w.elements, { count: assembled.elements.length })}
      </h3>
      <ul
        className="max-h-[max(14rem,calc(100dvh-37rem))] divide-y divide-shell-line/60 overflow-y-auto rounded-lg border border-shell-line"
        data-testid="context-elements"
      >
        {assembled.elements.map((element) => {
          const key = `${element.kind}-${element.ref_id}`;
          return (
            <ElementRow
              key={key}
              element={element}
              names={names}
              open={open === key}
              onToggle={() => setOpen(open === key ? null : key)}
              at={{ contextId: assembled.context_id, version: assembled.version }}
              canFeedback={canMake}
            />
          );
        })}
      </ul>
    </section>
  );
}

function ElementRow({
  element,
  names,
  open,
  onToggle,
  at,
  canFeedback,
}: {
  element: ContextElement;
  names: ReadonlyMap<string, ContextElement>;
  open: boolean;
  onToggle: () => void;
  /** The version it is shown from: inspected there (LEKA-376). */
  at: { contextId: string; version: number };
  /** Whether what is said of it may be said (LEKA-375). */
  canFeedback: boolean;
}) {
  const t = useDictionary();
  const w = t.environment.sheet.context;
  const Icon = element.entity ? typeIcon(element.entity.type) : ArrowRight;
  const kinds = [...new Set(element.provenance.sources.map((s) => s.kind).filter(Boolean))];
  return (
    <li className="px-3 py-2 text-[0.8125rem]" data-testid="context-element">
      <div className="flex items-center gap-2">
        <Icon className="size-4 shrink-0 text-shell-nav-active" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate">
          <Said element={element} />
        </span>
        <span className="hidden shrink-0 text-xs text-shell-muted sm:inline">
          {reasonText(t, element, names)}
        </span>
        <RowMarks element={element} />
        <span className="flex shrink-0 gap-1">
          {kinds.map((kind) => (
            <Logo key={kind} kind={kind as string} className="size-4" />
          ))}
        </span>
        <button
          type="button"
          aria-expanded={open}
          aria-label={fill(w.provenanceOf, { label: element.label })}
          onClick={onToggle}
          className="rounded p-0.5 text-shell-muted outline-none hover:text-brand-navy focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        >
          <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
        </button>
      </div>
      {open ? <Provenance element={element} names={names} /> : null}
      {open ? (
        <ElementInspect contextId={at.contextId} version={at.version} refId={element.ref_id} />
      ) : null}
      {open && canFeedback ? (
        <div className="mt-2 ms-6">
          <ElementFeedback contextId={at.contextId} version={at.version} refId={element.ref_id} />
        </div>
      ) : null}
    </li>
  );
}

/** An element in words: an entity by its name and type; a relationship as
 * the sentence it says. */
function Said({ element }: { element: ContextElement }) {
  const t = useDictionary();
  if (element.entity) {
    return (
      <>
        <Link
          href={entityHref({ id: element.ref_id, type: element.entity.type })}
          className="font-medium text-brand-navy outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        >
          {element.entity.name}
        </Link>{" "}
        <span className="text-xs text-shell-muted">{typeLabel(t, element.entity.type)}</span>
      </>
    );
  }
  const tie = element.relationship;
  if (!tie) return <>{element.label}</>;
  const verb = (t.knowledge.relationships as Record<string, string>)[tie.type] ?? tie.type;
  return (
    <span className="text-brand-navy">
      {tie.start.name} <span className="text-shell-muted">{verb}</span> {tie.end.name}
    </span>
  );
}

function reasonText(
  t: Dictionary,
  element: ContextElement,
  names: ReadonlyMap<string, ContextElement>,
): string {
  const w = t.environment.sheet.context;
  const { reason } = element;
  if (reason.role === "root") return w.reason.root;
  if (reason.role === "tie") return w.reason.tie;
  if (reason.role === "found" || reason.depth === null) {
    const by = [...new Set(reason.retrievers.map((m) => retrieverName(t, m.retriever)))];
    return by.length ? fill(w.reason.foundBy, { by: by.join(", ") }) : w.reason.found;
  }
  const via = reason.via ? names.get(reason.via)?.relationship : null;
  const step = fill(w.reason.reached, { depth: reason.depth });
  if (!via) return step;
  const verb = (t.knowledge.relationships as Record<string, string>)[via.type] ?? via.type;
  return `${step} · ${fill(w.via, { relation: verb })}`;
}

function Provenance({
  element,
  names,
}: {
  element: ContextElement;
  names: ReadonlyMap<string, ContextElement>;
}) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.environment.sheet.context;
  const said = element.provenance;
  const attributes = Object.entries(said.attributes);
  const found = element.reason.retrievers;
  const seen = [
    said.first_seen_at ? fill(w.firstSeen, { ago: ago(t, said.first_seen_at) }) : null,
    said.last_seen_at ? fill(w.lastSeen, { ago: ago(t, said.last_seen_at) }) : null,
    said.changed_at ? fill(w.changed, { ago: ago(t, said.changed_at) }) : null,
  ].filter(Boolean);
  return (
    <dl
      className="mt-2 grid gap-x-4 gap-y-1 rounded-lg bg-shell-canvas p-3 text-xs sm:grid-cols-[9rem_minmax(0,1fr)]"
      data-testid="context-provenance"
    >
      <dt className="text-shell-muted">{w.why}</dt>
      <dd>{reasonText(t, element, names)}</dd>
      {found.length > 0 ? (
        <>
          <dt className="text-shell-muted">{w.foundBy}</dt>
          <dd>
            <ul>
              {found.map((match) => (
                <li key={`${match.retriever}-${match.rank}`}>
                  <span className="font-medium">{retrieverName(t, match.retriever)}</span>
                  {" · "}
                  {fill(w.rank, { rank: match.rank })}
                  {matchDetail(t, locale, match) ? ` · ${matchDetail(t, locale, match)}` : ""}
                </li>
              ))}
            </ul>
          </dd>
        </>
      ) : null}
      {element.ranking ? (
        <RankWhy ranking={element.ranking} />
      ) : element.relevance !== null && element.kind === "entity" ? (
        <>
          <dt className="text-shell-muted">{w.relevance}</dt>
          <dd className="tabular-nums">{Math.round(element.relevance * 100)} %</dd>
        </>
      ) : null}
      <dt className="text-shell-muted">{w.originLabel}</dt>
      <dd>
        {said.origin === "inferred"
          ? fill(w.origin.inferred, { rule: said.rule ?? "" })
          : w.origin.stated}
        {" · "}
        <ConfidenceBadge score={said.confidence} />
      </dd>
      <dt className="text-shell-muted">{w.sources}</dt>
      <dd>
        {said.sources.length === 0 ? (
          <span className="text-shell-muted">{w.noSource}</span>
        ) : (
          <ul>
            {said.sources.map((source) => (
              <li key={`${source.source_id}-${source.key ?? source.record_id ?? ""}`}>
                <span className="font-medium">{source.name ?? w.deletedSource}</span>
                {source.kind ? <span className="text-shell-muted"> ({source.kind})</span> : null}
                {source.key ? ` · ${fill(w.key, { key: source.key })}` : null}
                {source.record_id ? ` · ${fill(w.record, { record: source.record_id })}` : null}
              </li>
            ))}
          </ul>
        )}
      </dd>
      {said.evidence.length > 0 ? (
        <>
          <dt className="text-shell-muted">{w.evidence}</dt>
          <dd>{said.evidence.join(" · ")}</dd>
        </>
      ) : null}
      {said.inferred_from.length > 0 ? (
        <>
          <dt className="text-shell-muted">{w.inferredFrom}</dt>
          <dd>{said.inferred_from.map((id) => names.get(id)?.label ?? id).join(", ")}</dd>
        </>
      ) : null}
      {attributes.length > 0 ? (
        <>
          <dt className="text-shell-muted">{w.attributes}</dt>
          <dd>
            <ul>
              {origins(attributes).map(({ rule, score, names }) => (
                <li key={`${rule ?? ""}|${score}`}>
                  <span className="font-medium">
                    {rule === null ? w.attributeSource : fill(w.attributeRule, { rule, score })}
                  </span>{" "}
                  : {names.join(", ")}
                </li>
              ))}
            </ul>
          </dd>
        </>
      ) : null}
      {said.conflicts.length > 0 ? (
        <>
          <dt className="text-shell-muted">{w.conflicts}</dt>
          <dd>{said.conflicts.map((c) => String(c.attribute ?? "")).join(", ")}</dd>
        </>
      ) : null}
      {seen.length > 0 ? (
        <>
          <dt className="text-shell-muted">{w.seen}</dt>
          <dd>{seen.join(" · ")}</dd>
        </>
      ) : null}
      <dt className="text-shell-muted">{w.text}</dt>
      <dd className="font-mono break-words">{element.text}</dd>
    </dl>
  );
}

/** On what a retriever found it, in words: the steps, the words, the
 * event and when. */
function matchDetail(t: Dictionary, locale: string, match: RetrievalMatch): string | null {
  const w = t.environment.sheet.context;
  const detail = match.detail;
  if (match.retriever === "content") return w.found.content;
  if (!detail) return null;
  if (match.retriever === "graph") return fill(w.found.graph, { depth: detail });
  if (match.retriever === "search") return fill(w.found.words, { words: detail });
  if (match.retriever === "paths") return fill(w.found.path, { steps: detail.split(" ")[0] });
  if (match.retriever === "timeline") {
    const [kind, at] = detail.split(" ");
    const event = (w.events as Record<string, string>)[kind] ?? kind;
    return at ? fill(w.found.event, { event, at: exactDate(locale, at) }) : event;
  }
  return detail;
}

/** Attributes by where each came from: the sources first, then each
 * enrichment rule, with its confidence. */
function origins(
  attributes: [string, Record<string, unknown>][],
): { rule: string | null; score: number; names: string[] }[] {
  const grouped = new Map<string, { rule: string | null; score: number; names: string[] }>();
  for (const [name, origin] of attributes) {
    const rule = origin.origin === "enrichment" ? String(origin.rule ?? "") : null;
    const score = Math.round(Number(origin.confidence ?? 1) * 100);
    const key = rule === null ? "" : `${rule}|${score}`;
    const group = grouped.get(key) ?? { rule, score, names: [] };
    group.names.push(name);
    grouped.set(key, group);
  }
  return [...grouped.values()].sort((a, b) =>
    a.rule === null ? -1 : b.rule === null ? 1 : a.rule.localeCompare(b.rule),
  );
}

function Versions({
  rows,
  shown,
  onShow,
  onCompare,
}: {
  rows: readonly ContextVersion[];
  shown: number;
  onShow: (version: number) => void;
  onCompare: (pair: readonly [number, number]) => void;
}) {
  const t = useDictionary();
  const w = t.environment.sheet.context;
  return (
    <section aria-label={w.versions} className="rounded-lg border border-shell-line p-3">
      <h3 className="mb-2 text-[0.8125rem] font-semibold text-brand-navy">{w.versions}</h3>
      <ol className="max-h-64 space-y-2 overflow-y-auto" data-testid="context-versions">
        {rows.map((row) => (
          <li key={row.version} className="text-xs">
            <button
              type="button"
              onClick={() => onShow(row.version)}
              aria-current={row.version === shown ? "true" : undefined}
              className={cn(
                "w-full rounded-md px-2 py-1 text-start outline-none hover:bg-shell-canvas focus-visible:ring-2 focus-visible:ring-brand-violet/40",
                row.version === shown && "bg-brand-violet-soft",
              )}
            >
              <span className="block font-medium text-brand-navy">
                {fill(w.versionRow, {
                  version: row.version,
                  trigger: w.trigger[row.trigger],
                  ago: ago(t, row.assembled_at),
                })}
              </span>
              <span
                className={cn(
                  "block",
                  row.status === "failed" ? "text-state-danger" : "text-shell-muted",
                )}
              >
                {row.status === "failed"
                  ? fill(w.failedVersion, { error: row.error ?? "" })
                  : fill(w.versionCount, { count: row.element_count })}
                {row.reason ? ` · ${row.reason}` : ""}
              </span>
              <VersionWhy version={row} />
            </button>
            {row.version > 1 ? (
              <button
                type="button"
                onClick={() => onCompare([row.version - 1, row.version])}
                className="ms-2 rounded text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
              >
                {fill(w.compare, { previous: row.version - 1 })}
              </button>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

function Diff({ diff }: { diff: ContextDiff }) {
  const t = useDictionary();
  const w = t.environment.sheet.context;
  const fields = w.fields as Record<string, string>;
  const field = (name: string) =>
    name.startsWith("attributes.") ? name.slice("attributes.".length) : (fields[name] ?? name);
  return (
    <section
      aria-label={fill(w.diffTitle, { from: diff.from_version, to: diff.to_version })}
      className="rounded-lg border border-shell-line p-3 text-xs"
      data-testid="context-diff"
    >
      <h3 className="mb-1 text-[0.8125rem] font-semibold text-brand-navy">
        {fill(w.diffTitle, { from: diff.from_version, to: diff.to_version })}
      </h3>
      <p className="mb-2 text-shell-muted">
        {fill(w.diffSummary, {
          added: diff.added.length,
          removed: diff.removed.length,
          changed: diff.changed.length,
          same: diff.unchanged,
        })}
      </p>
      <ul className="max-h-48 space-y-1 overflow-y-auto">
        {diff.added.map((e) => (
          <li key={`a-${e.kind}-${e.ref_id}`} className="text-state-success">
            + {e.label}
          </li>
        ))}
        {diff.removed.map((e) => (
          <li key={`r-${e.kind}-${e.ref_id}`} className="text-state-danger">
            − {e.label}
          </li>
        ))}
        {diff.changed.map((c) => (
          <li key={`c-${c.after.kind}-${c.after.ref_id}`} className="text-state-warning">
            ~ {c.after.label}{" "}
            <span className="text-shell-muted">({c.fields.map(field).join(", ")})</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
