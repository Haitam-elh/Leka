"use client";

import { Bot, ClipboardCheck, ScrollText } from "lucide-react";
import { useState } from "react";

import { Card } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { useConfirm } from "@/components/interactions/confirm";
import { exactDate } from "@/components/knowledge/time";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { agentTitle } from "@/lib/agent-title";
import type { CustomRole } from "@/lib/access";
import type { AgentRun } from "@/lib/agent-runs";
import {
  AI_KINDS,
  updateOf,
  type AIControl,
  type AIControlEvent,
  type AIControlKind,
  type AIControlUpdate,
} from "@/lib/ai-governance";
import {
  useAIControlChange,
  useAIControls,
  useAIEvents,
  useAwaitingRuns,
  useRunDecision,
} from "@/lib/ai-governance-queries";
import { ApiError } from "@/lib/api";
import { fill, type Dictionary } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { useModelGateway } from "@/lib/models-queries";
import { notify } from "@/lib/notify";
import { personName } from "@/lib/team";
import { useTeamMembers } from "@/lib/team-queries";

/**
 * The workspace's AI, governed (LEKA-406): its controls — which models may
 * answer, how much may be asked, what an answer may not carry, which agents
 * wait for approval — the runs waiting, approved or rejected by someone
 * other than who asked, and what every control did. What the server refuses
 * is said as it says it.
 */

const SELECT = "h-9 rounded-md border border-shell-line bg-white px-2 text-sm";
const KIND_TONE = {
  model_access: "info",
  usage_limit: "warning",
  output_check: "violet",
  approval: "neutral",
} as const;
const OUTCOME_TONE: Record<string, "danger" | "warning" | "success" | "neutral" | "info"> = {
  refused: "danger",
  limited: "warning",
  redacted: "info",
  blocked: "danger",
  flagged: "warning",
  held: "neutral",
  approved: "success",
  rejected: "danger",
};

async function said<T>(t: Dictionary, work: Promise<T>, done: string): Promise<boolean> {
  try {
    await work;
    notify.success({ title: done });
    return true;
  } catch (error) {
    notify.error({ title: error instanceof ApiError ? error.message : t.governance.failed });
    return false;
  }
}

/** What the control does, in a line. */
export function controlSaid(t: Dictionary, c: AIControl): string {
  const w = t.governance.ai;
  const parts: string[] = [];
  if (c.kind === "model_access") {
    if (c.block) parts.push(w.noModel);
    else {
      const allowed = [...(c.providers ?? []), ...(c.owners ?? []).map((o) => w.ownersSaid[o])];
      parts.push(fill(w.allowsOnly, { what: allowed.join(", ") }));
    }
  } else if (c.kind === "usage_limit") {
    const what = [
      c.max_calls != null ? fill(w.calls, { count: c.max_calls }) : null,
      c.max_tokens != null ? fill(w.tokens, { count: c.max_tokens }) : null,
      c.max_cost_usd != null ? fill(w.cost, { count: c.max_cost_usd }) : null,
    ].filter(Boolean);
    parts.push(
      fill(w.limitSaid, {
        what: what.join(", "),
        period: w.periods[c.period ?? "day"],
        per: w.pers[c.per ?? "workspace"],
      }),
    );
  } else if (c.kind === "output_check") {
    parts.push(
      fill(w.findSaid, {
        what: (c.detect ?? []).map((d) => w.detects[d]).join(", "),
        action: w.onFindings[c.on_finding ?? "redact"],
      }),
    );
  } else {
    parts.push(
      fill(w.approvalSaid, {
        risk: (t.governance.risks as Record<string, string>)[c.risk_at_least ?? "high"],
      }),
    );
  }
  parts.push(c.purposes?.length ? c.purposes.join(", ") : w.forAll);
  if (c.roles?.length) parts.push(fill(t.governance.forRoles, { roles: c.roles.join(", ") }));
  return parts.join(" · ");
}

function Toggles<T extends string>({
  id,
  label,
  options,
  chosen,
  onChange,
}: {
  id: string;
  label: string;
  options: { value: T; label: string }[];
  chosen: T[];
  onChange: (next: T[]) => void;
}) {
  return (
    <fieldset className="flex flex-col gap-1" data-testid={id}>
      <legend className="mb-1 text-[0.8125rem] font-medium text-brand-navy">{label}</legend>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {options.map((o) => (
          <label key={o.value} className="flex items-center gap-1.5 text-xs text-brand-navy">
            <input
              type="checkbox"
              checked={chosen.includes(o.value)}
              onChange={(e) =>
                onChange(e.target.checked ? [...chosen, o.value] : chosen.filter((v) => v !== o.value))
              }
            />
            {o.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function amount(text: string): number | null {
  const value = Number(text);
  return text.trim() && Number.isFinite(value) && value >= 0 ? value : null;
}

export function AIControlsCard({ canManage, roles }: { canManage: boolean; roles: CustomRole[] }) {
  const t = useDictionary();
  const w = t.governance.ai;
  const confirm = useConfirm();
  const { data } = useAIControls();
  const gateway = useModelGateway();
  const change = useAIControlChange();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<AIControlKind>("output_check");
  const [purposes, setPurposes] = useState("");
  const [who, setWho] = useState<string[]>([]);
  const [providers, setProviders] = useState<string[]>([]);
  const [owners, setOwners] = useState<("leka" | "workspace")[]>([]);
  const [block, setBlock] = useState(false);
  const [period, setPeriod] = useState<"day" | "month">("day");
  const [per, setPer] = useState<"workspace" | "person">("workspace");
  const [calls, setCalls] = useState("");
  const [tokens, setTokens] = useState("");
  const [cost, setCost] = useState("");
  const [detect, setDetect] = useState<("secrets" | "personal_data")[]>(["secrets"]);
  const [onFinding, setOnFinding] = useState<"redact" | "block" | "flag">("redact");
  const [risk, setRisk] = useState<"low" | "medium" | "high">("high");

  const providerChoices = (gateway.data?.providers ?? []).map((p) => ({ value: p.name, label: p.title }));
  const roleChoices = [
    { value: "member", label: t.governance.roles.member },
    { value: "admin", label: t.governance.roles.admin },
    ...roles.map((r) => ({ value: r.key, label: r.name })),
  ];

  async function create(event: React.FormEvent) {
    event.preventDefault();
    const body: AIControlUpdate = {
      name: name.trim(),
      kind,
      purposes: purposes
        .split(",")
        .map((p) => p.trim())
        .filter(Boolean),
      roles: who,
      enabled: true,
      providers,
      owners,
      block,
      period,
      per,
      max_calls: amount(calls),
      max_tokens: amount(tokens),
      max_cost_usd: amount(cost),
      detect,
      on_finding: onFinding,
      risk_at_least: risk,
    };
    if (await said(t, change.create.mutateAsync(body), fill(w.saved, { name: body.name }))) {
      setName("");
      setPurposes("");
      setWho([]);
    }
  }

  function toggle(c: AIControl) {
    void said(
      t,
      change.update.mutateAsync({ id: c.id, body: { ...updateOf(c), enabled: !c.enabled } }),
      c.enabled ? w.off : w.on,
    );
  }

  async function remove(c: AIControl) {
    const ok = await confirm({
      title: fill(w.deleteTitle, { name: c.name }),
      confirmLabel: t.governance.delete,
      destructive: true,
    });
    if (ok) await said(t, change.remove.mutateAsync(c.id), fill(w.deleted, { name: c.name }));
  }

  return (
    <Card title={w.controls} icon={<Bot className="size-4 text-shell-muted" aria-hidden="true" />}>
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.controlsSaid}</p>
      {data?.length ? (
        <ul className="mb-4 flex flex-col gap-2" data-testid="ai-controls">
          {data.map((c) => (
            <li
              key={c.id}
              data-control={c.kind}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-shell-line p-3 text-[0.8125rem]"
            >
              <Pill tone={KIND_TONE[c.kind]}>{w.kinds[c.kind]}</Pill>
              <span className="font-medium text-brand-navy">{c.name}</span>
              {!c.enabled ? <Pill tone="neutral">{t.governance.off}</Pill> : null}
              <span className="w-full text-xs text-shell-muted">{controlSaid(t, c)}</span>
              {canManage ? (
                <span className="flex gap-2">
                  <Button type="button" size="sm" variant="outline" onClick={() => toggle(c)}>
                    {c.enabled ? t.governance.turnOff : t.governance.turnOn}
                  </Button>
                  <Button type="button" size="sm" variant="outline" onClick={() => void remove(c)}>
                    {t.governance.delete}
                  </Button>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-4 text-[0.8125rem] text-shell-muted">{w.none}</p>
      )}
      {canManage ? (
        <form className="flex flex-col gap-2" onSubmit={(e) => void create(e)} data-testid="ai-control-form">
          <label htmlFor="ai-control-name" className="text-[0.8125rem] font-medium text-brand-navy">
            {w.newControl}
          </label>
          <Input
            id="ai-control-name"
            placeholder={w.namePlaceholder}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
              {w.kind}
              <select className={SELECT} value={kind} onChange={(e) => setKind(e.target.value as AIControlKind)}>
                {AI_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {w.kinds[k]}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
              {w.purposes}
              <Input aria-label={w.purposes} value={purposes} placeholder="agent:*" onChange={(e) => setPurposes(e.target.value)} />
              <span className="text-xs text-shell-muted">{w.purposesHint}</span>
            </label>
          </div>
          {kind === "model_access" ? (
            <>
              <Toggles id="ai-providers" label={w.providers} options={providerChoices} chosen={providers} onChange={setProviders} />
              <Toggles
                id="ai-owners"
                label={w.owners}
                options={[
                  { value: "leka" as const, label: w.ownersSaid.leka },
                  { value: "workspace" as const, label: w.ownersSaid.workspace },
                ]}
                chosen={owners}
                onChange={setOwners}
              />
              <label className="flex items-center gap-1.5 text-xs text-brand-navy">
                <input type="checkbox" checked={block} onChange={(e) => setBlock(e.target.checked)} />
                {w.block}
              </label>
            </>
          ) : null}
          {kind === "usage_limit" ? (
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
                {w.period}
                <select className={SELECT} value={period} onChange={(e) => setPeriod(e.target.value as "day" | "month")}>
                  <option value="day">{w.periods.day}</option>
                  <option value="month">{w.periods.month}</option>
                </select>
              </label>
              <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
                {w.per}
                <select className={SELECT} value={per} onChange={(e) => setPer(e.target.value as "workspace" | "person")}>
                  <option value="workspace">{w.pers.workspace}</option>
                  <option value="person">{w.pers.person}</option>
                </select>
              </label>
              <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
                {w.maxCalls}
                <Input type="number" min={0} value={calls} onChange={(e) => setCalls(e.target.value)} />
              </label>
              <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
                {w.maxTokens}
                <Input type="number" min={0} value={tokens} onChange={(e) => setTokens(e.target.value)} />
              </label>
              <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
                {w.maxCost}
                <Input type="number" min={0} step="0.01" value={cost} onChange={(e) => setCost(e.target.value)} />
              </label>
            </div>
          ) : null}
          {kind === "output_check" ? (
            <>
              <Toggles
                id="ai-detect"
                label={w.detect}
                options={[
                  { value: "secrets" as const, label: w.detects.secrets },
                  { value: "personal_data" as const, label: w.detects.personal_data },
                ]}
                chosen={detect}
                onChange={setDetect}
              />
              <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
                {w.onFinding}
                <select
                  className={SELECT}
                  value={onFinding}
                  onChange={(e) => setOnFinding(e.target.value as "redact" | "block" | "flag")}
                >
                  <option value="redact">{w.onFindings.redact}</option>
                  <option value="block">{w.onFindings.block}</option>
                  <option value="flag">{w.onFindings.flag}</option>
                </select>
              </label>
            </>
          ) : null}
          {kind === "approval" ? (
            <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
              {w.riskAtLeast}
              <select className={SELECT} value={risk} onChange={(e) => setRisk(e.target.value as "low" | "medium" | "high")}>
                <option value="low">{t.governance.risks.low}</option>
                <option value="medium">{t.governance.risks.medium}</option>
                <option value="high">{t.governance.risks.high}</option>
              </select>
            </label>
          ) : null}
          <Toggles id="ai-roles" label={t.governance.appliesTo} options={roleChoices} chosen={who} onChange={setWho} />
          <div>
            <Button type="submit" disabled={name.trim().length < 2 || change.create.isPending}>
              {w.create}
            </Button>
          </div>
        </form>
      ) : null}
    </Card>
  );
}

export function ApprovalsCard({ canApprove }: { canApprove: boolean }) {
  const t = useDictionary();
  const w = t.governance.ai;
  const { format: locale } = useLocale();
  const { data } = useAwaitingRuns();
  const decide = useRunDecision();
  const members = useTeamMembers();
  const names = new Map((members.data ?? []).map((m) => [m.user_id, personName(m)]));

  function decided(run: AgentRun, approve: boolean) {
    void said(
      t,
      decide.mutateAsync({ id: run.id, approve }),
      approve ? w.approved : w.rejected,
    );
  }

  return (
    <Card title={w.approvals} icon={<ClipboardCheck className="size-4 text-shell-muted" aria-hidden="true" />}>
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.approvalsSaid}</p>
      {data?.length ? (
        <ul className="flex flex-col gap-2" data-testid="ai-approvals">
          {data.map((run) => (
            <li key={run.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-shell-line p-3 text-[0.8125rem]">
              <span className="font-medium text-brand-navy">{agentTitle(t, run.key, run.title ?? run.key)}</span>
              <span className="text-xs text-shell-muted">
                {run.mine ? w.yours : ((run.requested_by && names.get(run.requested_by)) || t.governance.someone)} ·{" "}
                {exactDate(locale, run.queued_at)}
              </span>
              {canApprove && !run.mine ? (
                <span className="ms-auto flex gap-2">
                  <Button type="button" size="sm" disabled={decide.isPending} onClick={() => decided(run, true)}>
                    {w.approve}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={decide.isPending}
                    onClick={() => decided(run, false)}
                  >
                    {w.reject}
                  </Button>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[0.8125rem] text-shell-muted">{w.noApproval}</p>
      )}
    </Card>
  );
}

function eventSaid(e: AIControlEvent, names: Map<string, string>, someone: string): string {
  return [
    e.control_name,
    e.purpose,
    e.model ? `${e.provider ?? ""} ${e.model}`.trim() : null,
    Array.isArray(e.detail.found) ? (e.detail.found as string[]).join(", ") : null,
    e.user_id ? (names.get(e.user_id) ?? someone) : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

export function AIAuditCard() {
  const t = useDictionary();
  const w = t.governance.ai;
  const { format: locale } = useLocale();
  const { data } = useAIEvents(true);
  const members = useTeamMembers();
  const names = new Map((members.data ?? []).map((m) => [m.user_id, personName(m)]));
  return (
    <Card title={w.audit} icon={<ScrollText className="size-4 text-shell-muted" aria-hidden="true" />}>
      {data?.length ? (
        <ul className="flex flex-col gap-1.5" data-testid="ai-audit">
          {data.map((e) => (
            <li key={e.id} className="flex flex-col gap-0.5 border-t border-shell-line pt-2 text-[0.8125rem]" data-outcome={e.outcome}>
              <span className="flex flex-wrap items-center gap-2">
                <Pill tone={OUTCOME_TONE[e.outcome] ?? "neutral"}>{w.outcomes[e.outcome]}</Pill>
                <span className="text-brand-navy">{eventSaid(e, names, t.governance.someone)}</span>
              </span>
              <span className="text-xs text-shell-muted">{exactDate(locale, e.at)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[0.8125rem] text-shell-muted">{w.noAudit}</p>
      )}
    </Card>
  );
}
