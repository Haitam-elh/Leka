"use client";

import { FlaskConical, Gavel, History, ShieldAlert, Trash2, UserCheck } from "lucide-react";
import { useState } from "react";

import { Card } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { useConfirm } from "@/components/interactions/confirm";
import { exactDate } from "@/components/knowledge/time";
import { actionWord, reasonSaid, RiskPill } from "@/components/decisions/decision-card";
import { useCurrentUser, usePermissions } from "@/components/shell/shell-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api";
import {
  type ApprovalPolicy,
  type DecisionGovernanceEvent,
  type PolicyVerdict,
  type Risk,
  RISKS,
  type RiskRule,
  windowState,
} from "@/lib/decisions";
import {
  useApprovalPolicy,
  useDelegate,
  useDelegations,
  useEvaluatePolicy,
  useGovernanceExceptions,
  useGovernanceHistory,
  useGrantException,
  useRevokeDelegation,
  useRevokeException,
  useSetPolicy,
} from "@/lib/decisions-queries";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import { personName, type TeamMember } from "@/lib/team";
import { useTeamMembers } from "@/lib/team-queries";

/**
 * Sécurité & gouvernance › Approbations (LEKA-404): the governance of
 * consequential actions, as the API keeps it — the policy per risk level
 * (approvals, four eyes, the role required, how long an approval holds,
 * when one waiting is escalated) and the rules that raise a risk, an
 * action simulated against them, the freezes and waivers, the delegations,
 * and the journal of every change. An admin changes the policy and the
 * exceptions; an approver lends their authority; everyone here reads.
 */

/** What LEKA can be asked to do to a system. */
const ACTIONS = ["restart", "rollback", "deploy", "scale", "stop", "update", "fix", "migrate"] as const;
const STATE_TONES = { active: "success", upcoming: "info", ended: "neutral", revoked: "neutral" } as const;

function failed(t: Dictionary, error: unknown): string {
  return error instanceof ApiError ? error.message : t.decisions.governance.failed;
}

function words(value: string): string[] {
  return value
    .split(",")
    .map((word) => word.trim())
    .filter(Boolean);
}

/** A datetime-local's value, as the API reads it — none when empty. */
function instant(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

function useNames(): (id: string | null | undefined) => string {
  const t = useDictionary();
  const members = useTeamMembers();
  return (id) => {
    const member = id ? members.data?.find((m) => m.user_id === id) : undefined;
    return member ? personName(member) : t.decisions.governance.someone;
  };
}

// ── the policy, per risk ─────────────────────────────────────────────────────

type Row = {
  approvals: number;
  separate: boolean;
  role: "admin" | "owner" | null;
  valid: number | null;
  escalate: number | null;
};

function rowsOf(policy: ApprovalPolicy): Record<Risk, Row> {
  return Object.fromEntries(
    RISKS.map((risk) => [
      risk,
      {
        approvals: policy.approvals[risk] ?? 1,
        separate: policy.separate.includes(risk),
        role: policy.roles[risk] ?? null,
        valid: policy.valid_hours[risk] ?? null,
        escalate: policy.escalate_hours[risk] ?? null,
      },
    ]),
  ) as Record<Risk, Row>;
}

function hours(value: string): number | null {
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function PolicyCard({ policy, editable }: { policy: ApprovalPolicy; editable: boolean }) {
  const t = useDictionary();
  const w = t.decisions.governance;
  const save = useSetPolicy();
  const [rows, setRows] = useState(() => rowsOf(policy));
  const [raises, setRaises] = useState(policy.production_raises);
  const set = (risk: Risk, change: Partial<Row>) => setRows({ ...rows, [risk]: { ...rows[risk], ...change } });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    try {
      await save.mutateAsync({
        approvals: Object.fromEntries(RISKS.map((r) => [r, rows[r].approvals])),
        separate: RISKS.filter((r) => rows[r].separate),
        roles: Object.fromEntries(RISKS.map((r) => [r, rows[r].role])),
        valid_hours: Object.fromEntries(RISKS.map((r) => [r, rows[r].valid])),
        escalate_hours: Object.fromEntries(RISKS.map((r) => [r, rows[r].escalate])),
        production_raises: raises,
      });
      notify.success({ title: w.saved });
    } catch (error) {
      notify.error({ title: failed(t, error) });
    }
  }

  const cell = "px-2 py-1.5";
  const field = "w-16 rounded-md border border-shell-line bg-white px-2 py-1 text-brand-navy disabled:bg-shell-canvas";
  return (
    <Card
      title={w.policy}
      icon={<Gavel className="size-4 text-shell-muted" aria-hidden="true" />}
      action={<Pill tone={policy.customised ? "violet" : "neutral"}>{policy.customised ? w.customised : w.byDefault}</Pill>}
    >
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.policySaid}</p>
      <form onSubmit={(e) => void submit(e)} data-testid="approval-policy">
        <div className="overflow-x-auto">
          <table className="w-full text-[0.8125rem]">
            <thead>
              <tr className="text-left text-xs text-shell-muted">
                {(["risk", "approvals", "separate", "role", "valid", "escalate"] as const).map((c) => (
                  <th key={c} className={`${cell} font-medium`} scope="col">
                    {w.columns[c]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {RISKS.map((risk) => (
                <tr key={risk} className="border-t border-shell-line" data-risk={risk}>
                  <th scope="row" className={`${cell} text-left font-normal`}>
                    <RiskPill risk={risk} />
                  </th>
                  <td className={cell}>
                    <select
                      aria-label={`${w.columns.approvals} · ${t.decisions.risks[risk]}`}
                      className="rounded-md border border-shell-line bg-white px-2 py-1 text-brand-navy disabled:bg-shell-canvas"
                      disabled={!editable}
                      value={rows[risk].approvals}
                      onChange={(e) => set(risk, { approvals: Number(e.target.value) })}
                    >
                      {[1, 2, 3, 4, 5].map((n) => (
                        <option key={n} value={n}>
                          {n}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className={cell}>
                    <input
                      type="checkbox"
                      aria-label={`${w.columns.separate} · ${t.decisions.risks[risk]}`}
                      disabled={!editable}
                      checked={rows[risk].separate}
                      onChange={(e) => set(risk, { separate: e.target.checked })}
                    />
                  </td>
                  <td className={cell}>
                    <select
                      aria-label={`${w.columns.role} · ${t.decisions.risks[risk]}`}
                      className="rounded-md border border-shell-line bg-white px-2 py-1 text-brand-navy disabled:bg-shell-canvas"
                      disabled={!editable}
                      value={rows[risk].role ?? ""}
                      onChange={(e) => set(risk, { role: (e.target.value || null) as Row["role"] })}
                    >
                      <option value="">{w.roles.none}</option>
                      <option value="admin">{w.roles.admin}</option>
                      <option value="owner">{w.roles.owner}</option>
                    </select>
                  </td>
                  {(["valid", "escalate"] as const).map((key) => (
                    <td key={key} className={cell}>
                      <input
                        type="number"
                        min={1}
                        max={720}
                        placeholder={w.never}
                        aria-label={`${w.columns[key]} · ${t.decisions.risks[risk]}`}
                        className={field}
                        disabled={!editable}
                        value={rows[risk][key] ?? ""}
                        onChange={(e) => set(risk, { [key]: hours(e.target.value) })}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <label className="mt-3 flex items-center gap-2 text-[0.8125rem] text-brand-navy">
          <input
            type="checkbox"
            disabled={!editable}
            checked={raises}
            onChange={(e) => setRaises(e.target.checked)}
          />
          {w.productionRaises}
        </label>
        {editable ? (
          <Button type="submit" className="mt-3" disabled={save.isPending} data-testid="approval-policy-save">
            {w.save}
          </Button>
        ) : (
          <p className="mt-3 text-xs text-shell-muted">{w.readOnly}</p>
        )}
      </form>
    </Card>
  );
}

// ── the rules ────────────────────────────────────────────────────────────────

export function ruleSaid(t: Dictionary, rule: RiskRule): string {
  const w = t.decisions.governance;
  const c = w.conditions;
  const parts = [
    rule.actions?.length ? fill(c.actions, { list: rule.actions.map((a) => actionWord(t, a)).join(", ") }) : w.anyAction,
    rule.environments?.length ? fill(c.environments, { list: rule.environments.join(", ") }) : null,
    rule.target_types?.length ? fill(c.target_types, { list: rule.target_types.join(", ") }) : null,
    rule.target_criticality?.length
      ? fill(c.target_criticality, { list: rule.target_criticality.join(", ") })
      : null,
    rule.reversible === true ? c.reversible : rule.reversible === false ? c.irreversible : null,
  ].filter(Boolean);
  return fill(w.ruleLine, {
    conditions: parts.join(" · "),
    level: (t.decisions.levels as Record<string, string>)[rule.at_least] ?? rule.at_least,
  });
}

function RulesCard({ rules, editable }: { rules: RiskRule[]; editable: boolean }) {
  const t = useDictionary();
  const w = t.decisions.governance;
  const save = useSetPolicy();
  const [name, setName] = useState("");
  const [atLeast, setAtLeast] = useState<Risk>("high");
  const [actions, setActions] = useState<string[]>([]);
  const [environments, setEnvironments] = useState("");
  const [types, setTypes] = useState("");
  const [criticality, setCriticality] = useState("");
  const [reversible, setReversible] = useState<"any" | "yes" | "no">("any");

  async function keep(next: RiskRule[], said: string) {
    try {
      await save.mutateAsync({ rules: next });
      notify.success({ title: said });
      return true;
    } catch (error) {
      notify.error({ title: failed(t, error) });
      return false;
    }
  }

  async function add(event: React.FormEvent) {
    event.preventDefault();
    const rule: RiskRule = {
      name: name.trim(),
      at_least: atLeast,
      actions,
      environments: words(environments),
      target_types: words(types),
      target_criticality: words(criticality),
      reversible: reversible === "any" ? null : reversible === "yes",
    };
    if (await keep([...rules, rule], w.rulesSaved)) {
      setName("");
      setActions([]);
      setEnvironments("");
      setTypes("");
      setCriticality("");
      setReversible("any");
    }
  }

  return (
    <Card title={w.rules} icon={<ShieldAlert className="size-4 text-shell-muted" aria-hidden="true" />}>
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.rulesSaid}</p>
      {rules.length ? (
        <ul className="mb-4 flex flex-col gap-2" data-testid="risk-rules">
          {rules.map((rule) => (
            <li
              key={rule.name}
              data-rule={rule.name}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-shell-line p-3 text-[0.8125rem]"
            >
              <span className="min-w-0 flex-1">
                <span className="font-medium text-brand-navy">
                  {(t.decisions.ruleNames as Record<string, string>)[rule.name] ?? rule.name}
                </span>
                <span className="block text-shell-muted">{ruleSaid(t, rule)}</span>
              </span>
              {editable ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={save.isPending}
                  onClick={() => void keep(rules.filter((r) => r.name !== rule.name), w.rulesSaved)}
                >
                  <Trash2 className="size-4" aria-hidden="true" />
                  {w.removeRule}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-4 text-[0.8125rem] text-shell-muted">{w.noRule}</p>
      )}
      {editable ? (
        <form className="flex flex-col gap-2 text-[0.8125rem]" onSubmit={(e) => void add(e)} data-testid="risk-rule-form">
          <p className="font-medium text-brand-navy">{w.addRule}</p>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1">
              <span className="text-shell-muted">{w.ruleName}</span>
              <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-shell-muted">{w.ruleLevel}</span>
              <select
                className="rounded-md border border-shell-line bg-white px-2 py-1.5 text-brand-navy"
                value={atLeast}
                onChange={(e) => setAtLeast(e.target.value as Risk)}
              >
                {RISKS.map((risk) => (
                  <option key={risk} value={risk}>
                    {t.decisions.impact[risk]}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <fieldset className="flex flex-wrap gap-x-3 gap-y-1">
            <legend className="mb-1 text-shell-muted">{w.ruleActions}</legend>
            {ACTIONS.map((action) => (
              <label key={action} className="flex items-center gap-1 text-brand-navy">
                <input
                  type="checkbox"
                  checked={actions.includes(action)}
                  onChange={(e) =>
                    setActions(e.target.checked ? [...actions, action] : actions.filter((a) => a !== action))
                  }
                />
                {actionWord(t, action)}
              </label>
            ))}
          </fieldset>
          <label className="flex flex-col gap-1">
            <span className="text-shell-muted">{w.ruleEnvironments}</span>
            <Input value={environments} onChange={(e) => setEnvironments(e.target.value)} placeholder="production" />
          </label>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1">
              <span className="text-shell-muted">{w.ruleTypes}</span>
              <Input value={types} onChange={(e) => setTypes(e.target.value)} placeholder="database" />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-shell-muted">{w.ruleCriticality}</span>
              <Input value={criticality} onChange={(e) => setCriticality(e.target.value)} placeholder="critical" />
            </label>
          </div>
          <select
            aria-label={w.ruleReversible.any}
            className="w-fit rounded-md border border-shell-line bg-white px-2 py-1.5 text-brand-navy"
            value={reversible}
            onChange={(e) => setReversible(e.target.value as "any" | "yes" | "no")}
          >
            {(["any", "yes", "no"] as const).map((v) => (
              <option key={v} value={v}>
                {w.ruleReversible[v]}
              </option>
            ))}
          </select>
          <div>
            <Button type="submit" disabled={!name.trim() || save.isPending}>
              {w.addRule}
            </Button>
          </div>
        </form>
      ) : null}
    </Card>
  );
}

// ── an action, simulated ─────────────────────────────────────────────────────

function Verdict({ verdict }: { verdict: PolicyVerdict }) {
  const t = useDictionary();
  const w = t.decisions;
  return (
    <div className="mt-3 flex flex-col gap-2 rounded-lg border border-shell-line p-3 text-[0.8125rem]" data-testid="policy-verdict">
      <div className="flex flex-wrap items-center gap-2">
        <RiskPill risk={verdict.risk} />
        <span className="text-brand-navy">
          {fill(w.governance.verdict, { count: verdict.approvals })}
          {verdict.separate ? ` ${w.separate}` : ""}
          {verdict.role ? `, ${(w.roleRequired as Record<string, string>)[verdict.role] ?? verdict.role}` : ""}
        </span>
      </div>
      <ul className="flex flex-col gap-0.5 text-brand-navy">
        {verdict.reasons.map((reason, index) => (
          <li key={index}>· {reasonSaid(t, reason)}</li>
        ))}
      </ul>
      {verdict.frozen ? <p className="text-state-info">{w.governance.verdictFrozen}</p> : null}
      {verdict.waived ? <p className="text-state-success">{w.governance.verdictWaived}</p> : null}
    </div>
  );
}

function SimulateCard() {
  const t = useDictionary();
  const w = t.decisions.governance;
  const evaluate = useEvaluatePolicy();
  const [action, setAction] = useState<string>("restart");
  const [environment, setEnvironment] = useState("production");
  const [risk, setRisk] = useState<"" | "low" | "medium" | "high">("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    try {
      await evaluate.mutateAsync({
        action,
        environment: environment.trim() || null,
        risk: risk || null,
        targets: [],
      });
    } catch (error) {
      notify.error({ title: failed(t, error) });
    }
  }

  const select = "rounded-md border border-shell-line bg-white px-2 py-1.5 text-brand-navy";
  return (
    <Card title={w.simulate} icon={<FlaskConical className="size-4 text-shell-muted" aria-hidden="true" />}>
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.simulateSaid}</p>
      <form className="flex flex-wrap items-end gap-2 text-[0.8125rem]" onSubmit={(e) => void submit(e)} data-testid="policy-simulate">
        <label className="flex flex-col gap-1">
          <span className="text-shell-muted">{w.action}</span>
          <select className={select} value={action} onChange={(e) => setAction(e.target.value)}>
            {ACTIONS.map((a) => (
              <option key={a} value={a}>
                {actionWord(t, a)}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-shell-muted">{w.environment}</span>
          <Input value={environment} onChange={(e) => setEnvironment(e.target.value)} className="w-36" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-shell-muted">{w.analysisRisk}</span>
          <select className={select} value={risk} onChange={(e) => setRisk(e.target.value as typeof risk)}>
            <option value="">{w.unsaid}</option>
            {(["low", "medium", "high"] as const).map((r) => (
              <option key={r} value={r}>
                {t.decisions.impact[r]}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" disabled={evaluate.isPending}>
          {w.evaluate}
        </Button>
      </form>
      {evaluate.data ? <Verdict verdict={evaluate.data} /> : null}
    </Card>
  );
}

// ── freezes and waivers ──────────────────────────────────────────────────────

function ExceptionsCard({ editable }: { editable: boolean }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.decisions.governance;
  const names = useNames();
  const confirm = useConfirm();
  const { data } = useGovernanceExceptions();
  const grant = useGrantException();
  const revoke = useRevokeException();
  const [kind, setKind] = useState<"freeze" | "waiver">("freeze");
  const [reason, setReason] = useState("");
  const [from, setFrom] = useState("");
  const [until, setUntil] = useState("");
  const [actions, setActions] = useState<string[]>([]);
  const [environments, setEnvironments] = useState("");
  const [maxRisk, setMaxRisk] = useState<"low" | "medium">("low");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const ends = instant(until);
    if (!ends) return;
    try {
      await grant.mutateAsync({
        kind,
        reason: reason.trim(),
        starts_at: instant(from),
        ends_at: ends,
        actions,
        environments: words(environments),
        targets: [],
        max_risk: maxRisk,
      });
      notify.success({ title: w.granted[kind] });
      setReason("");
      setFrom("");
      setUntil("");
      setActions([]);
      setEnvironments("");
    } catch (error) {
      notify.error({ title: failed(t, error) });
    }
  }

  async function end(id: string, which: "freeze" | "waiver") {
    const ok = await confirm({ title: w.revokeTitles[which], description: w.revokeSaid, confirmLabel: w.revoke });
    if (!ok) return;
    try {
      await revoke.mutateAsync(id);
      notify.success({ title: w.revoked });
    } catch (error) {
      notify.error({ title: failed(t, error) });
    }
  }

  return (
    <Card title={w.exceptions} icon={<ShieldAlert className="size-4 text-shell-muted" aria-hidden="true" />}>
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.exceptionsSaid}</p>
      {data?.length ? (
        <ul className="mb-4 flex flex-col gap-2" data-testid="governance-exceptions">
          {data.map((e) => {
            const state = windowState(e);
            const scope = [
              e.actions.length ? e.actions.map((a) => actionWord(t, a)).join(", ") : null,
              e.environments.length ? e.environments.join(", ") : null,
            ].filter(Boolean);
            return (
              <li
                key={e.id}
                data-exception={e.kind}
                data-state={state}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-shell-line p-3 text-[0.8125rem]"
              >
                <Pill tone={e.kind === "freeze" ? "info" : "violet"}>{w.kinds[e.kind]}</Pill>
                <Pill tone={STATE_TONES[state]}>{w.states[state]}</Pill>
                <span className="min-w-0 flex-1">
                  <span className="font-medium text-brand-navy">{e.reason}</span>
                  <span className="block text-shell-muted">
                    {scope.length ? scope.join(" · ") : w.everything}
                    {e.kind === "waiver" ? ` · ${t.decisions.impact[e.max_risk]}` : ""} ·{" "}
                    {fill(w.window, { from: exactDate(locale, e.starts_at), to: exactDate(locale, e.ends_at) })} ·{" "}
                    {names(e.granted_by)}
                  </span>
                </span>
                {editable && (state === "active" || state === "upcoming") ? (
                  <Button type="button" variant="outline" size="sm" onClick={() => void end(e.id, e.kind)}>
                    {w.revoke}
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mb-4 text-[0.8125rem] text-shell-muted">{w.noException}</p>
      )}
      {editable ? (
        <form className="flex flex-col gap-2 text-[0.8125rem]" onSubmit={(e) => void submit(e)} data-testid="exception-form">
          <p className="font-medium text-brand-navy">{w.grantTitle}</p>
          <div className="flex gap-3" role="radiogroup" aria-label={w.kind}>
            {(["freeze", "waiver"] as const).map((k) => (
              <label key={k} className="flex items-center gap-1 text-brand-navy">
                <input type="radio" name="exception-kind" checked={kind === k} onChange={() => setKind(k)} />
                {w.kinds[k]}
              </label>
            ))}
          </div>
          <label className="flex flex-col gap-1">
            <span className="text-shell-muted">{w.reason}</span>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} />
          </label>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1">
              <span className="text-shell-muted">{w.from}</span>
              <Input type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-shell-muted">{w.until}</span>
              <Input type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} />
            </label>
          </div>
          <fieldset className="flex flex-wrap gap-x-3 gap-y-1">
            <legend className="mb-1 text-shell-muted">{w.actions}</legend>
            {ACTIONS.map((action) => (
              <label key={action} className="flex items-center gap-1 text-brand-navy">
                <input
                  type="checkbox"
                  checked={actions.includes(action)}
                  onChange={(e) =>
                    setActions(e.target.checked ? [...actions, action] : actions.filter((a) => a !== action))
                  }
                />
                {actionWord(t, action)}
              </label>
            ))}
          </fieldset>
          <label className="flex flex-col gap-1">
            <span className="text-shell-muted">{w.environments}</span>
            <Input value={environments} onChange={(e) => setEnvironments(e.target.value)} placeholder="production" />
          </label>
          {kind === "waiver" ? (
            <label className="flex flex-col gap-1">
              <span className="text-shell-muted">{w.maxRisk}</span>
              <select
                className="w-fit rounded-md border border-shell-line bg-white px-2 py-1.5 text-brand-navy"
                value={maxRisk}
                onChange={(e) => setMaxRisk(e.target.value as "low" | "medium")}
              >
                <option value="low">{t.decisions.impact.low}</option>
                <option value="medium">{t.decisions.impact.medium}</option>
              </select>
            </label>
          ) : null}
          <div>
            <Button type="submit" disabled={reason.trim().length < 3 || !until || grant.isPending}>
              {w.grant}
            </Button>
          </div>
        </form>
      ) : null}
    </Card>
  );
}

// ── delegations ──────────────────────────────────────────────────────────────

function DelegationsCard({ canLend, isAdmin }: { canLend: boolean; isAdmin: boolean }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.decisions.governance;
  const me = useCurrentUser();
  const names = useNames();
  const confirm = useConfirm();
  const members = useTeamMembers();
  const { data } = useDelegations();
  const lend = useDelegate();
  const revoke = useRevokeDelegation();
  const [to, setTo] = useState("");
  const [maxRisk, setMaxRisk] = useState<Risk>("medium");
  const [until, setUntil] = useState("");
  const [reason, setReason] = useState("");
  const others = (members.data ?? []).filter((m: TeamMember) => m.user_id !== me?.id);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const ends = instant(until);
    if (!ends || !to) return;
    try {
      await lend.mutateAsync({ to, max_risk: maxRisk, reason: reason.trim(), ends_at: ends, starts_at: null });
      notify.success({ title: w.delegated });
      setTo("");
      setUntil("");
      setReason("");
    } catch (error) {
      notify.error({ title: failed(t, error) });
    }
  }

  async function end(id: string) {
    const ok = await confirm({ title: w.revokeDelegationTitle, description: w.revokeSaid, confirmLabel: w.revoke });
    if (!ok) return;
    try {
      await revoke.mutateAsync(id);
      notify.success({ title: w.revoked });
    } catch (error) {
      notify.error({ title: failed(t, error) });
    }
  }

  return (
    <Card title={w.delegations} icon={<UserCheck className="size-4 text-shell-muted" aria-hidden="true" />}>
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.delegationsSaid}</p>
      {data?.length ? (
        <ul className="mb-4 flex flex-col gap-2" data-testid="delegations">
          {data.map((d) => {
            const state = windowState(d);
            return (
              <li
                key={d.id}
                data-state={state}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-shell-line p-3 text-[0.8125rem]"
              >
                <Pill tone={STATE_TONES[state]}>{w.states[state]}</Pill>
                <span className="min-w-0 flex-1">
                  <span className="font-medium text-brand-navy">
                    {fill(w.delegationLine, {
                      by: names(d.delegated_by),
                      to: names(d.delegated_to),
                      level: (t.decisions.levels as Record<string, string>)[d.max_risk] ?? d.max_risk,
                    })}
                  </span>
                  <span className="block text-shell-muted">
                    {d.reason} ·{" "}
                    {fill(w.window, { from: exactDate(locale, d.starts_at), to: exactDate(locale, d.ends_at) })}
                  </span>
                </span>
                {(isAdmin || d.delegated_by === me?.id) && (state === "active" || state === "upcoming") ? (
                  <Button type="button" variant="outline" size="sm" onClick={() => void end(d.id)}>
                    {w.revoke}
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mb-4 text-[0.8125rem] text-shell-muted">{w.noDelegation}</p>
      )}
      {canLend ? (
        <form className="flex flex-col gap-2 text-[0.8125rem]" onSubmit={(e) => void submit(e)} data-testid="delegation-form">
          <div className="grid gap-2 sm:grid-cols-3">
            <label className="flex flex-col gap-1">
              <span className="text-shell-muted">{w.delegateTo}</span>
              <select
                className="rounded-md border border-shell-line bg-white px-2 py-1.5 text-brand-navy"
                value={to}
                onChange={(e) => setTo(e.target.value)}
              >
                <option value="" />
                {others.map((m) => (
                  <option key={m.user_id} value={m.user_id}>
                    {personName(m)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-shell-muted">{w.maxRisk}</span>
              <select
                className="rounded-md border border-shell-line bg-white px-2 py-1.5 text-brand-navy"
                value={maxRisk}
                onChange={(e) => setMaxRisk(e.target.value as Risk)}
              >
                {RISKS.map((risk) => (
                  <option key={risk} value={risk}>
                    {t.decisions.impact[risk]}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-shell-muted">{w.until}</span>
              <Input type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} />
            </label>
          </div>
          <label className="flex flex-col gap-1">
            <span className="text-shell-muted">{w.reason}</span>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} />
          </label>
          <div>
            <Button type="submit" disabled={!to || !until || reason.trim().length < 3 || lend.isPending}>
              {w.delegate}
            </Button>
          </div>
        </form>
      ) : null}
    </Card>
  );
}

// ── the journal ──────────────────────────────────────────────────────────────

function eventDetail(t: Dictionary, event: DecisionGovernanceEvent): string | null {
  const w = t.decisions.governance;
  const d = event.detail as Record<string, unknown>;
  if (event.kind === "policy_changed" && Array.isArray(d.changed)) {
    return fill(w.changed, {
      list: d.changed.map((k) => (w.policyKeys as Record<string, string>)[String(k)] ?? String(k)).join(", "),
    });
  }
  if (typeof d.reason === "string" && d.reason) return `« ${d.reason} »`;
  if (typeof d.risk === "string") return t.decisions.risks[d.risk as Risk] ?? d.risk;
  return null;
}

function JournalCard() {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.decisions.governance;
  const names = useNames();
  const { data } = useGovernanceHistory();
  return (
    <Card title={w.journal} icon={<History className="size-4 text-shell-muted" aria-hidden="true" />}>
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.journalSaid}</p>
      {data?.length ? (
        <ul className="flex flex-col gap-2" data-testid="governance-journal">
          {data.map((event) => {
            const detail = eventDetail(t, event);
            return (
              <li key={event.id} data-kind={event.kind} className="border-t border-shell-line pt-2 text-[0.8125rem]">
                <span className="font-medium text-brand-navy">
                  {(w.events as Record<string, string>)[event.kind] ?? event.kind}
                </span>
                {detail ? <span className="text-brand-navy"> · {detail}</span> : null}
                <span className="block text-xs text-shell-muted">
                  {event.by ? names(event.by) : w.byLeka} · {exactDate(locale, event.at)}
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-[0.8125rem] text-shell-muted">{w.noEvent}</p>
      )}
    </Card>
  );
}

export function ApprovalGovernance() {
  const permissions = usePermissions() ?? [];
  const isAdmin = permissions.includes("workspace:update");
  const canLend = permissions.includes("intention:approve");
  const policy = useApprovalPolicy();
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" data-testid="approval-governance">
      <div className="flex flex-col gap-4">
        {policy.data ? (
          <>
            <PolicyCard key={JSON.stringify(policy.data)} policy={policy.data} editable={isAdmin} />
            <RulesCard rules={policy.data.rules} editable={isAdmin} />
          </>
        ) : (
          <div className="h-64 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />
        )}
        <SimulateCard />
      </div>
      <div className="flex flex-col gap-4">
        <ExceptionsCard editable={isAdmin} />
        <DelegationsCard canLend={canLend} isAdmin={isAdmin} />
        <JournalCard />
      </div>
    </div>
  );
}
