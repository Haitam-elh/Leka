"use client";

import { Check, MessageSquareWarning, PencilLine, ShieldCheck, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { cn } from "cn";

import { entityHref } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { useConfirm } from "@/components/interactions/confirm";
import { timeAgo } from "@/components/knowledge/time";
import { useCurrentUser, usePermissions } from "@/components/shell/shell-provider";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  type Decision,
  type DecisionProposal,
  type DecisionVote,
  mayApprove,
  remaining,
  type VoteKind,
} from "@/lib/decisions";
import { useVote } from "@/lib/decisions-queries";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

/**
 * A decision on what an intention asks to do (LEKA-390), as À valider's
 * panel (mockup 09) and the intention's page show it: where it stands, at
 * which risk, how many must approve under the workspace's policy and how
 * many have; each action proposed — what, on what, where, within which
 * constraints, whether it can be undone; then, for who may decide, Valider,
 * Refuser, Modifier, Demander des modifications — the refusals said with
 * their reason — and every vote kept.
 *
 * Approving asks first and says what it opens the way to; refusing, asking
 * for changes and modifying ask why, which the API keeps with the vote.
 * Nothing is drawn that the API did not say.
 */

const STATUS_TONES = {
  proposed: "warning",
  approved: "success",
  rejected: "danger",
  changes_requested: "info",
  superseded: "neutral",
} as const;
const RISK_TONES = { low: "success", medium: "warning", high: "danger" } as const;

export function actionWord(t: Dictionary, action: string): string {
  return (t.intentions.understanding.actionNames as Record<string, string>)[action] ?? action;
}

/** "Redémarrer · Billing API · production". */
export function proposalTitle(t: Dictionary, proposal: DecisionProposal): string {
  return [
    actionWord(t, proposal.action),
    proposal.targets.map((target) => target.name).join(", "),
    proposal.environment,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function RiskPill({ risk }: { risk: Decision["risk"] }) {
  const t = useDictionary();
  return (
    <Pill tone={RISK_TONES[risk]} data-testid="decision-risk" data-risk={risk}>
      {t.decisions.risks[risk]}
    </Pill>
  );
}

export function DecisionStatusPill({ decision }: { decision: Decision }) {
  const t = useDictionary();
  return (
    <Pill
      tone={STATUS_TONES[decision.status]}
      data-testid="decision-status"
      data-status={decision.status}
    >
      {t.decisions.statuses[decision.status]}
    </Pill>
  );
}

function ProposalLine({ proposal }: { proposal: DecisionProposal }) {
  const t = useDictionary();
  const w = t.decisions;
  const kinds = t.intentions.understanding.scope.kinds as Record<string, string>;
  const reversible =
    proposal.reversible === true ? "yes" : proposal.reversible === false ? "no" : "unknown";
  return (
    <li className="rounded-lg border border-shell-line px-3 py-2" data-testid="decision-proposal">
      <p className="font-medium text-brand-navy">{actionWord(t, proposal.action)}</p>
      <p className="text-[0.8125rem] text-shell-muted">
        {proposal.targets.length ? (
          <>
            {fill(w.on, { names: "" }).trim()}{" "}
            {proposal.targets.map((target, index) => (
              <span key={target.id}>
                {index > 0 ? ", " : null}
                <Link
                  href={entityHref({ id: target.id, type: target.type })}
                  className="text-brand-navy hover:underline"
                >
                  {target.name}
                </Link>
              </span>
            ))}
          </>
        ) : null}
        {proposal.environment ? ` · ${fill(w.inEnvironment, { environment: proposal.environment })}` : null}
      </p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        <Pill tone={reversible === "no" ? "danger" : reversible === "yes" ? "success" : "neutral"}>
          {w.reversible[reversible]}
        </Pill>
      </div>
      {proposal.constraints.length ? (
        <p className="mt-1 text-xs text-brand-navy">
          {fill(w.constraints, {
            list: proposal.constraints
              .map((c) => {
                const kind = kinds[String(c.kind)] ?? String(c.kind);
                return c.value && c.value !== true ? `${kind} (${String(c.value)})` : kind;
              })
              .join(", "),
          })}
        </p>
      ) : null}
    </li>
  );
}

function VoteLine({ vote }: { vote: DecisionVote }) {
  const t = useDictionary();
  const w = t.decisions;
  const me = useCurrentUser();
  const who = vote.by && vote.by === me?.id ? w.by.you : w.by.someone;
  const from = vote.changes.from as { proposals?: DecisionProposal[] } | undefined;
  const to = vote.changes.to as { proposals?: DecisionProposal[] } | undefined;
  const moved =
    from?.proposals && to?.proposals
      ? fill(w.moved, {
          from: from.proposals.map((p) => proposalTitle(t, p)).join(" ; "),
          to: to.proposals.map((p) => proposalTitle(t, p)).join(" ; "),
        })
      : null;
  return (
    <li
      className="rounded-lg border border-shell-line px-3 py-2 text-sm"
      data-testid="decision-vote"
      data-verdict={vote.verdict}
    >
      <span className="font-medium text-brand-navy">{w.verdicts[vote.verdict]}</span>
      <span className="text-shell-muted"> {who}</span>
      <span className="block text-xs text-shell-muted">
        <time dateTime={vote.at}>{timeAgo(t, vote.at)}</time> ·{" "}
        {fill(w.revision, { revision: vote.revision })}
      </span>
      {moved ? <span className="block text-xs text-brand-navy">{moved}</span> : null}
      {vote.reason ? (
        <span className="block text-[0.8125rem] text-brand-navy">
          {fill(w.reasonSaid, { reason: vote.reason })}
        </span>
      ) : null}
    </li>
  );
}

/** Modifier: where it runs, which actions are kept, why — then approved. */
function ModifyForm({
  decision,
  pending,
  onCancel,
  onSubmit,
}: {
  decision: Decision;
  pending: boolean;
  onCancel: () => void;
  onSubmit: (body: { environment: string | null; keep: string[]; reason: string }) => void;
}) {
  const t = useDictionary();
  const w = t.decisions;
  const first = decision.proposals.find((p) => p.environment)?.environment ?? "";
  const [environment, setEnvironment] = useState(first);
  const [keep, setKeep] = useState<string[]>(decision.proposals.map((p) => p.id));
  const [reason, setReason] = useState("");
  return (
    <form
      className="flex flex-col gap-3 rounded-lg border border-brand-violet/40 bg-brand-violet-soft/30 p-3"
      data-testid="decision-modify"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit({
          environment: environment.trim() && environment.trim() !== first ? environment.trim() : null,
          keep,
          reason,
        });
      }}
    >
      <p className="font-semibold text-brand-navy">{w.modifyTitle}</p>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-shell-nav">{w.modifyEnvironment}</span>
        <input
          value={environment}
          onChange={(event) => setEnvironment(event.target.value)}
          list="decision-environments"
          className="rounded-md border border-shell-line bg-white px-2 py-1.5 text-brand-navy outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          data-testid="decision-modify-environment"
        />
        <datalist id="decision-environments">
          {["production", "staging", "preprod", "development"].map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
      </label>
      {decision.proposals.length > 1 ? (
        <fieldset className="flex flex-col gap-1 text-sm">
          <legend className="text-shell-nav">{w.modifyKeep}</legend>
          {decision.proposals.map((proposal) => (
            <label key={proposal.id} className="flex items-center gap-2 text-brand-navy">
              <input
                type="checkbox"
                checked={keep.includes(proposal.id)}
                onChange={(event) =>
                  setKeep(
                    event.target.checked
                      ? [...keep, proposal.id]
                      : keep.filter((id) => id !== proposal.id),
                  )
                }
              />
              {actionWord(t, proposal.action)}
            </label>
          ))}
        </fieldset>
      ) : null}
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-shell-nav">{w.modifyReason}</span>
        <textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          rows={2}
          className="rounded-md border border-shell-line bg-white px-2 py-1.5 text-brand-navy outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40"
          data-testid="decision-modify-reason"
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" disabled={pending} data-testid="decision-modify-submit">
          {w.modifyConfirm}
        </Button>
        <Button type="button" size="sm" variant="outline" onClick={onCancel}>
          {w.modifyCancel}
        </Button>
      </div>
    </form>
  );
}

function Actions({ decision }: { decision: Decision }) {
  const t = useDictionary();
  const w = t.decisions;
  const me = useCurrentUser();
  const steward = usePermissions()?.includes("intention:approve") ?? false;
  const confirm = useConfirm();
  const vote = useVote(decision.intention_id);
  const [modifying, setModifying] = useState(false);

  if (!decision.open) return null;
  if (!steward) return <p className="text-[0.8125rem] text-shell-muted">{w.notYours}</p>;
  const approvable = mayApprove(decision, me?.id, steward);
  const iApproved = Boolean(me?.id && decision.approvers.includes(me.id));
  const askerOnly = decision.separate_asker && decision.asked_by === me?.id;

  async function cast(kind: VoteKind, body: { reason?: string | null; environment?: string | null; keep?: string[] }) {
    if (kind !== "approve" && !(body.reason ?? "").trim()) {
      notify.error({ title: w.refusals.reason_required });
      return false;
    }
    try {
      await vote.mutateAsync({ kind, body });
      notify.success({ title: w.done[kind] });
      return true;
    } catch (error) {
      const refusal = error instanceof ApiError ? error.fieldErrors?.refusal : undefined;
      const said = refusal ? (w.refusals as Record<string, string>)[refusal] : undefined;
      notify.error({ title: said ?? (error instanceof ApiError ? error.message : String(error)) });
      return false;
    }
  }

  async function withReason(kind: "reject" | "request-changes") {
    const reject = kind === "reject";
    const reason = await confirm({
      title: reject ? w.rejectTitle : w.changesTitle,
      description: reject ? w.rejectBody : w.changesBody,
      confirmLabel: reject ? w.reject : w.requestChanges,
      destructive: reject,
      reasonLabel: w.reason,
    });
    if (reason !== null) await cast(kind, { reason });
  }

  return (
    <div className="flex flex-col gap-3" data-testid="decision-actions">
      {iApproved ? (
        <p className="text-[0.8125rem] text-brand-navy">
          {fill(w.youApproved, { count: remaining(decision) })}
        </p>
      ) : askerOnly ? (
        <p className="text-[0.8125rem] text-brand-navy">{w.askerOnly}</p>
      ) : null}
      {modifying ? (
        <ModifyForm
          decision={decision}
          pending={vote.isPending}
          onCancel={() => setModifying(false)}
          onSubmit={async (body) => {
            if (await cast("modify", body)) setModifying(false);
          }}
        />
      ) : (
        <div className="flex flex-wrap gap-2">
          {approvable ? (
            <Button
              type="button"
              disabled={vote.isPending}
              data-testid="decision-approve"
              className="bg-state-success text-white hover:bg-state-success/90"
              onClick={async () => {
                const yes = await confirm({
                  title: w.approveTitle,
                  description: w.approveBody,
                  confirmLabel: w.approve,
                  impact: decision.proposals.map((p) => proposalTitle(t, p)),
                });
                if (yes) await cast("approve", {});
              }}
            >
              <Check className="size-4" aria-hidden="true" />
              {w.approve}
            </Button>
          ) : null}
          <Button
            type="button"
            variant="outline"
            disabled={vote.isPending}
            data-testid="decision-reject"
            className="border-state-danger/40 text-state-danger hover:bg-state-danger-soft"
            onClick={() => void withReason("reject")}
          >
            <X className="size-4" aria-hidden="true" />
            {w.reject}
          </Button>
          {approvable ? (
            <Button
              type="button"
              variant="outline"
              disabled={vote.isPending}
              data-testid="decision-modify-open"
              onClick={() => setModifying(true)}
            >
              <PencilLine className="size-4" aria-hidden="true" />
              {w.modify}
            </Button>
          ) : null}
          <Button
            type="button"
            variant="outline"
            disabled={vote.isPending}
            data-testid="decision-request-changes"
            onClick={() => void withReason("request-changes")}
          >
            <MessageSquareWarning className="size-4" aria-hidden="true" />
            {w.requestChanges}
          </Button>
        </div>
      )}
    </div>
  );
}

export function DecisionCard({ decision, className }: { decision: Decision; className?: string }) {
  const t = useDictionary();
  const w = t.decisions;
  return (
    <section
      className={cn("flex flex-col gap-4", className)}
      data-testid="decision"
      data-status={decision.status}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-brand-navy">
          {fill(w.number, { number: decision.number })}
        </span>
        <DecisionStatusPill decision={decision} />
        <RiskPill risk={decision.risk} />
      </div>
      <p className="text-[0.8125rem] text-brand-navy" data-testid="decision-requirement">
        {fill(w.required, { count: decision.required_approvals })}
        {decision.separate_asker ? ` ${w.separate}` : ""}
        {" · "}
        {fill(w.progress, {
          done: Math.min(decision.approvers.length, decision.required_approvals),
          count: decision.required_approvals,
        })}
      </p>
      <div>
        <p className="mb-2 text-sm font-semibold text-brand-navy">{w.proposals}</p>
        <ul className="flex flex-col gap-2">
          {decision.proposals.map((proposal) => (
            <ProposalLine key={proposal.id} proposal={proposal} />
          ))}
        </ul>
      </div>
      {decision.open ? (
        <p className="flex items-start gap-2 rounded-lg bg-shell-highlight px-3 py-2 text-[0.8125rem] text-brand-navy">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-shell-nav-active" aria-hidden="true" />
          {w.control}
        </p>
      ) : null}
      <Actions decision={decision} />
      <div>
        <p className="mb-2 text-sm font-semibold text-brand-navy">{w.votes}</p>
        {decision.votes.length ? (
          <ol className="flex flex-col gap-2" data-testid="decision-votes">
            {[...decision.votes].reverse().map((vote) => (
              <VoteLine key={vote.id} vote={vote} />
            ))}
          </ol>
        ) : (
          <p className="text-sm text-shell-muted">{w.noVotes}</p>
        )}
      </div>
    </section>
  );
}
