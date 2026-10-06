"use client";

import { Check, RotateCcw, Scale, X } from "lucide-react";
import { useState } from "react";

import { cn } from "cn";
import { aboutWord, sideWord, wordConflict } from "@/components/approvals/items";
import { ConflictBadge } from "@/components/approvals/parts";
import { useConfirm } from "@/components/interactions/confirm";
import { timeAgo } from "@/components/knowledge/time";
import { usePermissions } from "@/components/shell/shell-provider";
import { SourceLogo, sourceTitle } from "@/components/sources/source-logo";
import { ErrorState } from "@/components/states/error-state";
import { LoadingState } from "@/components/states/loading-state";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/tabs";
import type { ConflictDetail } from "@/lib/conflicts";
import { useArbitration, useConflict } from "@/lib/conflicts-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

type SourceKind = Parameters<typeof sourceTitle>[0];

/**
 * One conflict, beside the list (LEKA-382): what the model shows, what each
 * source says — how much it is believed, when it said it, the workspace's
 * rule on it — which side LEKA recommends and why; every decision taken.
 * Who may approve keeps a side (remembering its source, if they say so),
 * says it is no contradiction, or reopens what was decided — what came of
 * it said in the panel, not in a toast over its buttons.
 */
export function ConflictPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const t = useDictionary();
  const c = t.approvals.conflict;
  const found = useConflict(id);

  if (found.isPending) {
    return (
      <aside className="self-start rounded-xl border border-shell-line bg-white p-4">
        <LoadingState />
      </aside>
    );
  }
  if (found.isError) {
    return (
      <aside className="self-start rounded-xl border border-shell-line bg-white p-4">
        <ErrorState error={found.error} onRetry={() => void found.refetch()} />
      </aside>
    );
  }
  const conflict = found.data;
  const { title, why } = wordConflict(t, conflict);

  return (
    <aside
      aria-label={fill(c.panel.label, { title })}
      data-testid="conflict-panel"
      className="flex flex-col gap-4 self-start rounded-xl border border-shell-line bg-white p-4 xl:sticky xl:top-4"
    >
      <header className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-violet-soft text-shell-nav-active">
          <Scale className="size-5" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base leading-snug font-semibold text-brand-navy">{title}</h2>
          {why ? <p className="text-sm text-shell-muted">{why}</p> : null}
          <div className="mt-1.5">
            <ConflictBadge conflict={conflict} />
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t.approvals.panel.close}
          className="rounded p-1 text-shell-muted outline-none hover:text-brand-navy focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </header>

      <Tabs defaultValue="details">
        <TabsList>
          <TabsTab value="details">{t.approvals.panel.details}</TabsTab>
          <TabsTab value="history">{t.approvals.panel.history}</TabsTab>
        </TabsList>
        <TabsPanel value="details" className="flex flex-col gap-4 pt-4">
          <Arbitration key={conflict.id} conflict={conflict} />
        </TabsPanel>
        <TabsPanel value="history" className="pt-4">
          <History conflict={conflict} />
        </TabsPanel>
      </Tabs>
    </aside>
  );
}

/** The sides, and what who may approve can do with them. */
function Arbitration({ conflict }: { conflict: ConflictDetail }) {
  const t = useDictionary();
  const c = t.approvals.conflict;
  const p = c.panel;
  const confirm = useConfirm();
  const { resolve, dismiss, reopen } = useArbitration();
  const mayDecide = usePermissions()?.includes("intention:approve") ?? false;
  const busy = resolve.isPending || dismiss.isPending || reopen.isPending;
  const [remember, setRemember] = useState(false);
  const [said, setSaid] = useState<string | null>(null);
  const failed = () => {
    setSaid(null);
    notify.error({ title: t.approvals.toast.failed });
  };
  const decidable = conflict.status !== "gone";
  const recommended = conflict.recommendation.side;
  const kept = conflict.status === "resolved" ? conflict.resolution?.side : undefined;
  const reasons = conflict.recommendation.reasons
    .map((reason) => (c.reasons as Record<string, string>)[reason] ?? reason)
    .join(", ");

  const onKeep = (side: number) =>
    resolve.mutate(
      { id: conflict.id, side, remember },
      { onSuccess: () => setSaid(p.said.resolved), onError: failed },
    );
  const onDismiss = async () => {
    const reason = await confirm({
      title: c.confirm.dismissTitle,
      description: c.confirm.dismissBody,
      confirmLabel: c.confirm.dismissConfirm,
      reasonLabel: c.confirm.reason,
    });
    if (reason === null) return;
    dismiss.mutate(
      { id: conflict.id, reason },
      { onSuccess: () => setSaid(p.said.dismissed), onError: failed },
    );
  };
  const onReopen = () =>
    reopen.mutate(
      { id: conflict.id },
      { onSuccess: () => setSaid(p.said.reopened), onError: failed },
    );

  return (
    <>
      {conflict.kind === "attribute" && conflict.chosen !== null ? (
        <p className="rounded-lg bg-shell-canvas px-3 py-2 text-sm text-brand-navy">
          <span className="text-shell-muted">{p.model} </span>
          <span className="font-medium">{sideWord(t, conflict, conflict.chosen)}</span>
        </p>
      ) : null}

      <section className="flex flex-col gap-2">
        <h3 className="text-sm font-semibold text-brand-navy">{p.sides}</h3>
        <ol className="flex flex-col gap-2" data-testid="conflict-sides">
          {conflict.sides.map((side, index) => (
            <li
              key={`${index}:${JSON.stringify(side.value)}`}
              className={cn(
                "rounded-lg border px-3 py-2",
                index === recommended ? "border-brand-violet" : "border-shell-line",
              )}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-brand-navy">
                  {sideWord(t, conflict, side.value)}
                </span>
                {index === recommended ? (
                  <span className="rounded-md bg-brand-violet-soft px-1.5 py-0.5 text-[0.6875rem] font-medium text-shell-nav-active">
                    {p.recommended}
                  </span>
                ) : null}
                {index === kept ? (
                  <span className="rounded-md bg-state-success-soft px-1.5 py-0.5 text-[0.6875rem] font-medium text-state-success">
                    {p.kept}
                  </span>
                ) : null}
              </div>
              <ul className="mt-1 flex flex-col gap-0.5 text-xs text-shell-muted">
                {side.sources.length === 0 ? <li>{p.noSource}</li> : null}
                {side.sources.map((source, at) => (
                  <li key={`${source.source_id}:${at}`} className="flex flex-wrap items-center gap-1">
                    {source.kind ? (
                      <SourceLogo kind={source.kind as SourceKind} className="size-3.5" />
                    ) : null}
                    <span className="text-brand-navy">
                      {source.name ?? (source.kind ? sourceTitle(source.kind as SourceKind) : "—")}
                    </span>
                    <span>· {fill(p.authority, { score: Math.round(source.authority * 100) })}</span>
                    {source.observed_at ? (
                      <span>
                        · {fill(p.observed, { when: timeAgo(t, source.observed_at).toLowerCase() })}
                      </span>
                    ) : null}
                    {source.rule ? (
                      <span className="font-medium text-shell-nav-active">· {p.rule[source.rule]}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
              {mayDecide && decidable && index !== kept ? (
                <Button
                  size="sm"
                  variant={index === recommended ? "default" : "outline"}
                  onClick={() => onKeep(index)}
                  disabled={busy}
                  className="mt-2"
                  data-testid={`keep-${index}`}
                >
                  <Check aria-hidden="true" />
                  {p.keep}
                </Button>
              ) : null}
            </li>
          ))}
        </ol>
        {recommended !== null && reasons ? (
          <p className="text-xs text-shell-muted">{reasons}</p>
        ) : null}
      </section>

      {mayDecide ? (
        <section className="flex flex-col gap-2 border-t border-shell-line pt-4">
          <h3 className="text-sm font-semibold text-brand-navy">{t.approvals.panel.actions}</h3>
          <p role="status" className="text-xs font-medium text-state-success empty:hidden">
            {said}
          </p>
          {decidable ? (
            <label className="flex items-start gap-2 text-xs text-brand-navy">
              <input
                type="checkbox"
                checked={remember}
                onChange={(event) => setRemember(event.target.checked)}
                className="mt-0.5"
              />
              {fill(p.remember, { about: aboutWord(t, conflict.about) })}
            </label>
          ) : null}
          {conflict.kind === "relationship" && decidable ? (
            <p className="text-xs text-shell-muted">{p.refuted}</p>
          ) : null}
          {conflict.status === "resolved" ? (
            <p className="text-xs text-shell-muted">{p.applied}</p>
          ) : null}
          {conflict.status === "open" ? (
            <Button variant="outline" onClick={() => void onDismiss()} disabled={busy}>
              {p.dismiss}
            </Button>
          ) : null}
          {conflict.status === "resolved" || conflict.status === "dismissed" ? (
            <Button variant="outline" onClick={onReopen} disabled={busy}>
              <RotateCcw aria-hidden="true" />
              {p.reopen}
            </Button>
          ) : null}
        </section>
      ) : (
        <p className="text-xs text-shell-muted">{t.approvals.panel.readOnly}</p>
      )}
    </>
  );
}

function History({ conflict }: { conflict: ConflictDetail }) {
  const t = useDictionary();
  const p = t.approvals.conflict.panel;
  if (conflict.history.length === 0) {
    return <p className="text-sm text-shell-muted">{t.approvals.panel.noHistory}</p>;
  }
  const decided = p.decided as Record<string, string>;
  const via = t.approvals.panel.via as Record<string, string>;
  return (
    <ol className="flex flex-col gap-2 text-sm" data-testid="conflict-history">
      {[...conflict.history].reverse().map((entry, index) => (
        <li
          key={`${String(entry.at)}:${index}`}
          className="rounded-lg border border-shell-line px-3 py-2"
        >
          <span className="font-medium text-brand-navy">
            {decided[String(entry.status)] ?? String(entry.status)}
          </span>
          {entry.value !== undefined && entry.value !== null ? (
            <span className="text-brand-navy"> · {sideWord(t, conflict, entry.value)}</span>
          ) : null}
          {entry.via ? <span className="text-shell-muted"> {via[String(entry.via)]}</span> : null}
          <span className="block text-xs text-shell-muted">{timeAgo(t, String(entry.at))}</span>
          {entry.reason ? (
            <span className="block text-[0.8125rem] text-brand-navy">
              {fill(t.approvals.panel.reasonSaid, { reason: String(entry.reason) })}
            </span>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
