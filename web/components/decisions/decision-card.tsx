"use client";

import {
  AlarmClock,
  Check,
  Hourglass,
  MessageSquareWarning,
  PencilLine,
  ShieldAlert,
  ShieldCheck,
  Snowflake,
  Stamp,
  X,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { cn } from "cn";

import { entityHref } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { useConfirm } from "@/components/interactions/confirm";
import { exactDate, timeAgo } from "@/components/knowledge/time";
import { useCurrentUser, usePermissions } from "@/components/shell/shell-provider";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  type Decision,
  type DecisionProposal,
  type DecisionVote,
  lentTo,
  mayApprove,
  remaining,
  type Risk,
  type VoteKind,
} from "@/lib/decisions";
import { useDelegations, useVote } from "@/lib/decisions-queries";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import { personName } from "@/lib/team";
import { useTeamMembers } from "@/lib/team-queries";

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
 *
 * Its governance (LEKA-404): why it is at its risk, the role one approver
 * must hold, a freeze or a waiver that covered it when it opened, when it
 * is or was escalated, how long its approval holds — and, for someone an
 * approver lent their authority to, a vote in that approver's name.
 */

const STATUS_TONES = {
  proposed: "warning",
  approved: "success",
  rejected: "danger",
  changes_requested: "info",
  superseded: "neutral",
} as const;
const RISK_TONES = { low: "success", medium: "warning", high: "danger", critical: "danger" } as const;

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
    <Pill
      tone={RISK_TONES[risk]}
      dot={risk === "critical"}
      data-testid="decision-risk"
      data-risk={risk}
    >
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

function level(t: Dictionary, risk: unknown): string {
  return (t.decisions.levels as Record<string, string>)[String(risk)] ?? String(risk);
}

/** "Irréversible en production : au moins critique" — one reason of its risk. */
export function reasonSaid(t: Dictionary, reason: Record<string, unknown>): string {
  const w = t.decisions;
  const params = (reason.params ?? {}) as Record<string, unknown>;
  const code = String(reason.code);
  if (code === "analysis") return fill(w.reasons.analysis, { level: level(t, params.risk) });
  if (code === "rule") {
    const name = String(params.rule ?? "");
    return fill(w.reasons.rule, {
      rule: (w.ruleNames as Record<string, string>)[name] ?? `« ${name} »`,
      level: level(t, params.at_least),
    });
  }
  return (w.reasons as Record<string, string>)[code] ?? code;
}

/** Why it is at its risk; a freeze or a waiver that covered it; when it is
 * escalated; how long its approval holds. */
function Governance({ decision }: { decision: Decision }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.decisions;
  const g = decision.governance;
  if (!g) return null;
  const reasons = g.reasons ?? [];
  const said = (kind: string) =>
    (g.exceptions ?? []).find((e) => e.kind === kind) as Record<string, unknown> | undefined;
  const freeze = said("freeze");
  const waiver = said("waiver");
  const notes: { key: string; icon: React.ReactNode; text: string; tone?: string }[] = [];
  if (g.frozen && freeze && decision.open) {
    notes.push({
      key: "frozen",
      icon: <Snowflake className="mt-0.5 size-4 shrink-0" aria-hidden="true" />,
      text: fill(w.frozen, {
        reason: String(freeze.reason ?? ""),
        until: exactDate(locale, String(freeze.ends_at)),
      }),
      tone: "bg-state-info-soft text-state-info",
    });
  }
  if (g.grounding) {
    // What the action rests on is missing or stale (LEKA-436): blocked, or one more approval.
    const missing = [
      ...g.grounding.missing.map((name) => (w.grounding.evidence as Record<string, string>)[name] ?? name),
      ...g.grounding.stale.map(() => w.grounding.evidence.stale),
    ];
    notes.push({
      key: "grounding",
      icon: <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />,
      text: fill(g.grounding.gate === "blocked" ? w.grounding.blocked : w.grounding.validation, {
        missing: [...new Set(missing)].join(", "),
      }),
      tone:
        g.grounding.gate === "blocked"
          ? "bg-state-danger-soft text-state-danger"
          : "bg-state-warning-soft text-state-warning",
    });
  }
  if (g.waived && waiver) {
    notes.push({
      key: "waived",
      icon: <Stamp className="mt-0.5 size-4 shrink-0" aria-hidden="true" />,
      text: fill(w.waived, { reason: String(waiver.reason ?? "") }),
    });
  }
  if (g.escalated_at) {
    notes.push({
      key: "escalated",
      icon: <AlarmClock className="mt-0.5 size-4 shrink-0" aria-hidden="true" />,
      text: fill(w.escalatedOn, { when: timeAgo(t, g.escalated_at) }),
      tone: "bg-state-warning-soft text-state-warning",
    });
  } else if (g.escalate_at && decision.open) {
    notes.push({
      key: "escalates",
      icon: <AlarmClock className="mt-0.5 size-4 shrink-0" aria-hidden="true" />,
      text: fill(w.escalatesAt, { date: exactDate(locale, g.escalate_at) }),
    });
  }
  if (g.valid_until && decision.status === "approved") {
    notes.push({
      key: "valid",
      icon: <Hourglass className="mt-0.5 size-4 shrink-0" aria-hidden="true" />,
      text: fill(w.validUntil, { date: exactDate(locale, g.valid_until) }),
    });
  }
  if (!reasons.length && !notes.length) return null;
  return (
    <div className="flex flex-col gap-2" data-testid="decision-governance">
      {reasons.length ? (
        <div>
          <p className="mb-1 text-sm font-semibold text-brand-navy">{w.why}</p>
          <ul className="flex flex-col gap-0.5 text-[0.8125rem] text-brand-navy" data-testid="decision-reasons">
            {reasons.map((reason, index) => (
              <li key={index}>· {reasonSaid(t, reason)}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {notes.map((note) => (
        <p
          key={note.key}
          data-testid={`decision-${note.key}`}
          className={cn(
            "flex items-start gap-2 rounded-lg px-3 py-2 text-[0.8125rem]",
            note.tone ?? "bg-shell-highlight text-brand-navy",
          )}
        >
          {note.icon}
          {note.text}
        </p>
      ))}
    </div>
  );
}

/** "au nom de Ada Lovelace" — read only for a vote cast with an authority lent. */
function OnBehalf({ id }: { id: string }) {
  const t = useDictionary();
  const members = useTeamMembers();
  const member = members.data?.find((m) => m.user_id === id);
  const name = member ? personName(member) : t.decisions.governance.someone;
  return (
    <span className="text-shell-muted" data-testid="decision-vote-for">
      {" "}
      {fill(t.decisions.onBehalf, { name })}
    </span>
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
      {vote.on_behalf_of ? <OnBehalf id={vote.on_behalf_of} /> : null}
      {vote.role ? (
        <span className="text-shell-muted">
          {" "}
          ({(w.asRole as Record<string, string>)[vote.role] ?? vote.role})
        </span>
      ) : null}
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

/** Whose authority to vote with: one's own, or one lent (LEKA-404). */
function Authority({
  lenders,
  steward,
  value,
  onChange,
}: {
  lenders: string[];
  steward: boolean;
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  const t = useDictionary();
  const w = t.decisions;
  const members = useTeamMembers();
  const name = (id: string) => {
    const member = members.data?.find((m) => m.user_id === id);
    return member ? personName(member) : id.slice(0, 8);
  };
  return (
    <label className="flex flex-wrap items-center gap-2 text-[0.8125rem] text-brand-navy">
      <span>{w.voteAs}</span>
      <select
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value || null)}
        className="rounded-md border border-shell-line bg-white px-2 py-1 text-brand-navy"
        data-testid="decision-authority"
      >
        {steward ? <option value="">{w.voteAsMe}</option> : null}
        {lenders.map((id) => (
          <option key={id} value={id}>
            {fill(w.voteFor, { name: name(id) })}
          </option>
        ))}
      </select>
    </label>
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
  const delegations = useDelegations(decision.open);
  const lenders = [
    ...new Set(lentTo(delegations.data, me?.id, decision.risk as Risk).map((d) => d.delegated_by)),
  ];
  const [chosen, setChosen] = useState<string | null>(null);
  // A member votes only with an authority lent: the first, unless they choose.
  const authority = chosen ?? (steward ? null : (lenders[0] ?? null));

  if (!decision.open) return null;
  if (!steward && !lenders.length) {
    return <p className="text-[0.8125rem] text-shell-muted">{w.notYours}</p>;
  }
  const approvable = mayApprove(decision, me?.id, steward, authority);
  const whose = authority ?? me?.id;
  const iApproved = Boolean(whose && decision.approvers.includes(whose));
  const askerOnly =
    decision.separate_asker && (decision.asked_by === me?.id || decision.asked_by === authority);

  async function cast(kind: VoteKind, raw: { reason?: string | null; environment?: string | null; keep?: string[] }) {
    const body = authority ? { ...raw, on_behalf_of: authority } : raw;
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
      {lenders.length ? (
        <Authority lenders={lenders} steward={steward} value={authority} onChange={setChosen} />
      ) : null}
      {authority ? <p className="text-xs text-shell-muted">{w.lent}</p> : null}
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
        {decision.governance?.escalated_at && decision.open ? (
          <Pill tone="warning" data-testid="decision-escalated-pill">
            {w.escalated}
          </Pill>
        ) : null}
      </div>
      <p className="text-[0.8125rem] text-brand-navy" data-testid="decision-requirement">
        {fill(w.required, { count: decision.required_approvals })}
        {decision.separate_asker ? ` ${w.separate}` : ""}
        {decision.governance?.required_role
          ? `, ${(w.roleRequired as Record<string, string>)[decision.governance.required_role] ?? decision.governance.required_role}`
          : ""}
        {" · "}
        {fill(w.progress, {
          done: Math.min(decision.approvers.length, decision.required_approvals),
          count: decision.required_approvals,
        })}
      </p>
      <Governance decision={decision} />
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
