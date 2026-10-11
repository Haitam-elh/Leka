"use client";

import { ArrowRight, Check, RotateCcw, Sparkles, TriangleAlert, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { CandidateBadge, FAMILY_ICON } from "@/components/approvals/parts";
import { levelWord, wordCandidate } from "@/components/approvals/words";
import { useConfirm } from "@/components/interactions/confirm";
import { MetadataPanel } from "@/components/knowledge/metadata-panel";
import { timeAgo } from "@/components/knowledge/time";
import { usePermissions } from "@/components/shell/shell-provider";
import { SourceLogo, sourceTitle } from "@/components/sources/source-logo";
import { ErrorState } from "@/components/states/error-state";
import { LoadingState } from "@/components/states/loading-state";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/tabs";
import { routes } from "@/config/routes";
import type { CandidateDetail } from "@/lib/enrichment";
import { useCandidate, useDecisions } from "@/lib/enrichment-queries";
import { typeSegment } from "@/lib/environment";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

type SourceKind = Parameters<typeof sourceTitle>[0];

/**
 * One proposal, beside the list — the right-hand panel of mockup 09.
 *
 * Details: what it would change in the model — the relationship, or the
 * attribute as it is and as proposed; a warning when it replaces what a
 * source states — what shows it, how sure, where it was read. Decisions:
 * every one taken, who, how, why. And the actions for who may approve:
 * accept (an override asked twice), reject (why, optionally), reprocess —
 * what came of one said in the panel, not in a toast: a toast would sit on
 * the panel's buttons, there, in the corner, when the next decision is
 * the undoing of this one.
 */
export function CandidatePanel({ id, onClose }: { id: string; onClose: () => void }) {
  const t = useDictionary();
  const p = t.approvals.panel;
  const found = useCandidate(id);

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
  const candidate = found.data;
  const { title, why } = wordCandidate(t, candidate);
  const Icon = FAMILY_ICON[candidate.family] ?? Sparkles;

  return (
    <aside
      aria-label={fill(p.label, { title })}
      data-testid="candidate-panel"
      className="flex flex-col gap-4 self-start rounded-xl border border-shell-line bg-white p-4 xl:sticky xl:top-4"
    >
      <header className="flex items-start gap-3">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-brand-violet-soft text-shell-nav-active">
          <Icon className="size-5" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-base font-semibold leading-snug text-brand-navy">{title}</h2>
          {why ? <p className="text-sm text-shell-muted">{why}</p> : null}
          <div className="mt-1.5">
            <CandidateBadge candidate={candidate} />
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={p.close}
          className="rounded p-1 text-shell-muted outline-none hover:text-brand-navy focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </header>

      <Tabs defaultValue="details">
        <TabsList>
          <TabsTab value="details">{p.details}</TabsTab>
          <TabsTab value="history">{p.history}</TabsTab>
        </TabsList>
        <TabsPanel value="details" className="flex flex-col gap-4 pt-4">
          <Change candidate={candidate} />
          <Facts candidate={candidate} />
          <Evidence candidate={candidate} />
        </TabsPanel>
        <TabsPanel value="history" className="pt-4">
          <History candidate={candidate} />
        </TabsPanel>
      </Tabs>

      <Actions key={candidate.id} candidate={candidate} />
    </aside>
  );
}

function EntityLink({ thing }: { thing: CandidateDetail["subject"] }) {
  if (!thing.id || !thing.kind) return <span>{thing.name}</span>;
  return (
    <Link
      href={routes.entity(typeSegment(thing.kind), thing.id)}
      className="font-medium text-shell-nav-active underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
    >
      {thing.name}
    </Link>
  );
}

/** What it would change in the model. */
function Change({ candidate }: { candidate: CandidateDetail }) {
  const t = useDictionary();
  const p = t.approvals.panel;
  const relationships = t.approvals.relationships as Record<string, string>;
  const attributes = t.approvals.attributes as Record<string, string>;
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold text-brand-navy">{p.change}</h3>
      {candidate.kind === "relationship" && candidate.start && candidate.end ? (
        <p className="rounded-lg bg-shell-canvas px-3 py-2 text-sm text-brand-navy" data-testid="candidate-change">
          <EntityLink thing={candidate.start} />{" "}
          {relationships[candidate.relationship ?? ""] ?? candidate.relationship}{" "}
          <EntityLink thing={candidate.end} />
        </p>
      ) : (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-lg bg-shell-canvas px-3 py-2 text-sm" data-testid="candidate-change">
          <dt className="text-shell-muted">{p.attribute}</dt>
          <dd className="text-brand-navy">
            {attributes[candidate.attribute ?? ""] ?? candidate.attribute} ·{" "}
            <EntityLink thing={candidate.subject} />
          </dd>
          <dt className="text-shell-muted">{p.now}</dt>
          <dd className="text-brand-navy">{shown(t, candidate, candidate.current) ?? p.nothing}</dd>
          <dt className="text-shell-muted">{p.proposed}</dt>
          <dd className="font-medium text-brand-navy">{shown(t, candidate, candidate.value)}</dd>
        </dl>
      )}
      {candidate.overrides ? (
        <p className="flex items-start gap-2 rounded-lg bg-state-warning-soft px-3 py-2 text-[0.8125rem] text-state-warning">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          {p.override}
        </p>
      ) : null}
    </section>
  );
}

function shown(t: Dictionary, candidate: CandidateDetail, value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (candidate.attribute === "criticality") return levelWord(t, value);
  return typeof value === "string" ? value : JSON.stringify(value);
}

function Facts({ candidate }: { candidate: CandidateDetail }) {
  const t = useDictionary();
  const p = t.approvals.panel;
  // The kinds of the sources it rests on, as the API gives them: github…
  const sources = (
    Array.isArray(candidate.provenance.sources) ? candidate.provenance.sources.map(String) : []
  ) as SourceKind[];
  return (
    <MetadataPanel
      sections={[
        {
          items: [
            {
              label: p.type,
              value: (t.approvals.family as Record<string, string>)[candidate.family] ?? candidate.family,
            },
            {
              label: p.by,
              value: fill(p.byValue, {
                analysis:
                  (t.approvals.analyses as Record<string, string>)[candidate.analyzer] ??
                  candidate.analyzer,
              }),
            },
            { label: p.confidence, value: `${Math.round(candidate.confidence * 100)} %` },
            { label: p.seen, value: timeAgo(t, candidate.last_seen_at) },
            {
              label: p.sources,
              value: sources.length ? (
                <span className="flex flex-wrap items-center gap-2">
                  {sources.map((kind) => (
                    <span key={kind} className="flex items-center gap-1">
                      <SourceLogo kind={kind} className="size-4" />
                      {sourceTitle(kind)}
                    </span>
                  ))}
                </span>
              ) : null,
            },
          ],
        },
      ]}
    />
  );
}

/** What shows it: the things, by name. What each shows is the API's
 * English — said to a reader in English, in the tooltip otherwise; the
 * proposal's own words already say why, in the reader's language. */
function Evidence({ candidate }: { candidate: CandidateDetail }) {
  const t = useDictionary();
  const { locale } = useLocale();
  if (candidate.evidence.length === 0) return null;
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-sm font-semibold text-brand-navy">{t.approvals.panel.evidence}</h3>
      <ul className="flex flex-col gap-1.5 text-[0.8125rem]" data-testid="candidate-evidence">
        {candidate.evidence.map((item) => (
          <li
            key={`${item.id}:${item.detail}`}
            title={item.detail}
            className="rounded-lg border border-shell-line px-3 py-2"
          >
            <span className="font-medium text-brand-navy">{item.name}</span>
            {locale === "en" ? <span className="block text-shell-muted">{item.detail}</span> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function History({ candidate }: { candidate: CandidateDetail }) {
  const t = useDictionary();
  const p = t.approvals.panel;
  if (candidate.history.length === 0) {
    return <p className="text-sm text-shell-muted">{p.noHistory}</p>;
  }
  const decided = p.decided as Record<string, string>;
  const via = p.via as Record<string, string>;
  return (
    <ol className="flex flex-col gap-2 text-sm" data-testid="candidate-history">
      {[...candidate.history].reverse().map((entry, index) => (
        <li key={`${String(entry.at)}:${index}`} className="rounded-lg border border-shell-line px-3 py-2">
          <span className="font-medium text-brand-navy">
            {decided[String(entry.status)] ?? String(entry.status)}
          </span>
          {entry.via ? <span className="text-shell-muted"> {via[String(entry.via)]}</span> : null}
          <span className="block text-xs text-shell-muted">{timeAgo(t, String(entry.at))}</span>
          {entry.reason ? (
            <span className="block text-[0.8125rem] text-brand-navy">
              {fill(p.reasonSaid, { reason: String(entry.reason) })}
            </span>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

/** What who may approve can do, where it stands. */
function Actions({ candidate }: { candidate: CandidateDetail }) {
  const t = useDictionary();
  const p = t.approvals.panel;
  const c = t.approvals.confirm;
  const confirm = useConfirm();
  const { accept, reject, reprocess } = useDecisions();
  const mayDecide = usePermissions()?.includes("intention:approve") ?? false;
  const busy = accept.isPending || reject.isPending || reprocess.isPending;
  const [said, setSaid] = useState<string | null>(null);
  const failed = () => {
    setSaid(null);
    notify.error({ title: t.approvals.toast.failed });
  };

  if (!mayDecide) {
    return <p className="text-xs text-shell-muted">{p.readOnly}</p>;
  }

  const onAccept = async () => {
    if (
      candidate.overrides &&
      !(await confirm({
        title: c.overrideTitle,
        description: c.overrideBody,
        confirmLabel: c.overrideConfirm,
      }))
    ) {
      return;
    }
    accept.mutate(
      { id: candidate.id, override: candidate.overrides },
      { onSuccess: () => setSaid(t.approvals.toast.accepted), onError: failed },
    );
  };
  const onReject = async () => {
    const reason = await confirm({
      title: c.rejectTitle,
      description: c.rejectBody,
      confirmLabel: c.rejectConfirm,
      destructive: true,
      reasonLabel: c.reason,
    });
    if (reason === null) return;
    reject.mutate(
      { id: candidate.id, reason },
      { onSuccess: () => setSaid(t.approvals.toast.rejected), onError: failed },
    );
  };
  const onReprocess = () =>
    reprocess.mutate(
      { id: candidate.id },
      { onSuccess: () => setSaid(t.approvals.toast.reprocessed), onError: failed },
    );

  return (
    <section className="flex flex-col gap-2 border-t border-shell-line pt-4">
      <h3 className="text-sm font-semibold text-brand-navy">{p.actions}</h3>
      <p role="status" className="text-xs font-medium text-state-success empty:hidden">
        {said}
      </p>
      {candidate.status === "proposed" ? (
        <div className="grid grid-cols-2 gap-2">
          <Button onClick={() => void onAccept()} disabled={busy} className="bg-state-success hover:bg-state-success/90">
            <Check aria-hidden="true" />
            {p.accept}
          </Button>
          <Button variant="outline" onClick={() => void onReject()} disabled={busy} className="border-state-danger text-state-danger">
            <X aria-hidden="true" />
            {p.reject}
          </Button>
        </div>
      ) : null}
      {candidate.status === "accepted" ? (
        <>
          <p className="text-xs text-shell-muted">{p.applied}</p>
          <Button variant="outline" onClick={() => void onReject()} disabled={busy} className="border-state-danger text-state-danger">
            <X aria-hidden="true" />
            {p.reject}
          </Button>
        </>
      ) : null}
      {candidate.status === "rejected" || candidate.status === "withdrawn" ? (
        <>
          <Button variant="outline" onClick={onReprocess} disabled={busy}>
            <RotateCcw aria-hidden="true" />
            {p.reprocess}
          </Button>
          <p className="text-xs text-shell-muted">{p.reprocessHint}</p>
        </>
      ) : null}
      {candidate.status === "proposed" ? (
        <button
          type="button"
          onClick={onReprocess}
          disabled={busy}
          className="flex items-center gap-1 self-start rounded text-xs font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        >
          {p.reprocess}
          <ArrowRight className="rtl:-scale-x-100 size-3" aria-hidden="true" />
        </button>
      ) : null}
    </section>
  );
}
