"use client";

import { History, Scale, UserCog } from "lucide-react";
import { useState } from "react";

import { permissionSaid } from "@/components/governance/governance-screen";
import { Card } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { useConfirm } from "@/components/interactions/confirm";
import { exactDate } from "@/components/knowledge/time";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AccessModel, CustomRole, GovernanceEvent, Policy, PolicyUpdate } from "@/lib/access";
import {
  useAssignments,
  useCustomRoles,
  useGovernanceHistory,
  usePolicies,
  usePolicyChange,
} from "@/lib/access-queries";
import { ApiError } from "@/lib/api";
import { fill, type Dictionary } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import { personName, type TeamMember } from "@/lib/team";
import { useTeamMembers } from "@/lib/team-queries";

/**
 * Roles and policies of the workspace's own (LEKA-403): roles built on the
 * member's or the admin's — what they add, what they take away — given to a
 * person whose seat has that base; policies refusing, or allowing by
 * exception, at a priority; every change in their history. What the server
 * refuses is said as it says it.
 */

const OWNER_ONLY = new Set(["workspace:delete", "workspace:transfer", "audit:manage"]);
const ACTIONS = ["agent:run", "workflow:run"] as const;

function slug(name: string): string {
  return name
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

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

function Checks({
  id,
  label,
  options,
  chosen,
  onChange,
}: {
  id: string;
  label: string;
  options: { value: string; label: string }[];
  chosen: Set<string>;
  onChange: (next: Set<string>) => void;
}) {
  return (
    <fieldset className="flex flex-col gap-1" data-testid={id}>
      <legend className="mb-1 text-[0.8125rem] font-medium text-brand-navy">{label}</legend>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {options.map((o) => (
          <label key={o.value} className="flex items-center gap-1.5 text-xs text-brand-navy">
            <input
              type="checkbox"
              checked={chosen.has(o.value)}
              onChange={(e) => {
                const next = new Set(chosen);
                if (e.target.checked) next.add(o.value);
                else next.delete(o.value);
                onChange(next);
              }}
            />
            {o.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function RolesCard({ model, canManage }: { model: AccessModel; canManage: boolean }) {
  const t = useDictionary();
  const w = t.governance;
  const confirm = useConfirm();
  const { data: roles } = useCustomRoles();
  const { data: held } = useAssignments();
  const members = useTeamMembers();
  const change = usePolicyChange();
  const [name, setName] = useState("");
  const [base, setBase] = useState<"member" | "admin">("member");
  const [added, setAdded] = useState<Set<string>>(new Set());
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const basePermissions = new Set<string>(model.roles.find((r) => r.role === base)?.permissions ?? []);
  const holders = new Map((held ?? []).map((a) => [a.user_id, a.role]));
  const people = members.data ?? [];

  async function create(event: React.FormEvent) {
    event.preventDefault();
    const key = slug(name);
    const ok = await said(
      t,
      change.saveRole.mutateAsync({
        key,
        body: { name: name.trim(), base, added: [...added], removed: [...removed] },
      }),
      fill(w.roleSaved, { name: name.trim() }),
    );
    if (ok) {
      setName("");
      setAdded(new Set());
      setRemoved(new Set());
    }
  }

  async function remove(role: CustomRole) {
    const ok = await confirm({ title: fill(w.deleteRoleTitle, { name: role.name }), confirmLabel: w.delete, destructive: true });
    if (ok) await said(t, change.deleteRole.mutateAsync(role.key), fill(w.roleDeleted, { name: role.name }));
  }

  function give(member: TeamMember, key: string | null) {
    void said(t, change.assign.mutateAsync({ userId: member.user_id, role: key }), w.assigned);
  }

  return (
    <Card title={w.customRoles} icon={<UserCog className="size-4 text-shell-muted" aria-hidden="true" />}>
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.customRolesSaid}</p>
      {roles?.length ? (
        <ul className="mb-4 flex flex-col gap-3" data-testid="custom-roles">
          {roles.map((role) => (
            <li key={role.key} data-role={role.key} className="rounded-lg border border-shell-line p-3 text-[0.8125rem]">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-brand-navy">{role.name}</span>
                <Pill tone="neutral">
                  {fill(w.onBase, { base: (w.roles as Record<string, string>)[role.base] })}
                </Pill>
                <span className="text-xs text-shell-muted">{fill(w.holders, { count: role.holders })}</span>
                {canManage ? (
                  <Button type="button" variant="outline" size="sm" className="ml-auto" onClick={() => void remove(role)}>
                    {w.delete}
                  </Button>
                ) : null}
              </div>
              <p className="mt-1 text-xs text-shell-muted">
                {role.added.length ? `+ ${role.added.map((p) => permissionSaid(t, p)).join(", ")}` : ""}
                {role.added.length && role.removed.length ? " · " : ""}
                {role.removed.length ? `− ${role.removed.map((p) => permissionSaid(t, p)).join(", ")}` : ""}
              </p>
              {canManage ? (
                <div className="mt-2 flex flex-wrap gap-2">
                  {people
                    .filter((m) => m.role === role.base)
                    .map((m) => {
                      const has = holders.get(m.user_id) === role.key;
                      return (
                        <Button
                          key={m.user_id}
                          type="button"
                          size="sm"
                          variant={has ? "default" : "outline"}
                          aria-pressed={has}
                          onClick={() => give(m, has ? null : role.key)}
                        >
                          {personName(m)}
                        </Button>
                      );
                    })}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-4 text-[0.8125rem] text-shell-muted">{w.noCustomRole}</p>
      )}
      {canManage ? (
        <form className="flex flex-col gap-2" onSubmit={(e) => void create(e)} data-testid="role-form">
          <label htmlFor="role-name" className="text-[0.8125rem] font-medium text-brand-navy">
            {w.newRole}
          </label>
          <Input id="role-name" placeholder={w.roleNamePlaceholder} value={name} onChange={(e) => setName(e.target.value)} />
          <label htmlFor="role-base" className="text-[0.8125rem] font-medium text-brand-navy">
            {w.base}
          </label>
          <select
            id="role-base"
            className="h-9 rounded-md border border-shell-line bg-white px-2 text-sm"
            value={base}
            onChange={(e) => {
              setBase(e.target.value as "member" | "admin");
              setAdded(new Set());
              setRemoved(new Set());
            }}
          >
            <option value="member">{w.roles.member}</option>
            <option value="admin">{w.roles.admin}</option>
          </select>
          <Checks
            id="role-added"
            label={w.adds}
            options={model.permissions
              .filter((p) => !basePermissions.has(p) && !OWNER_ONLY.has(p))
              .map((p) => ({ value: p, label: permissionSaid(t, p) }))}
            chosen={added}
            onChange={setAdded}
          />
          <Checks
            id="role-removed"
            label={w.takesAway}
            options={model.permissions
              .filter((p) => basePermissions.has(p) && p !== "workspace:read")
              .map((p) => ({ value: p, label: permissionSaid(t, p) }))}
            chosen={removed}
            onChange={setRemoved}
          />
          <div>
            <Button type="submit" disabled={slug(name).length < 2 || change.saveRole.isPending}>
              {w.createRole}
            </Button>
          </div>
        </form>
      ) : null}
    </Card>
  );
}

function policySaid(t: Dictionary, p: Policy): string {
  const w = t.governance;
  const parts = [
    p.actions.map((a) => (a === "*" ? w.everyAction : permissionSaid(t, a))).join(", "),
    p.roles?.length ? fill(w.forRoles, { roles: p.roles.join(", ") }) : w.forEveryone,
  ];
  if (p.risk_at_least) parts.push(fill(w.riskAtLeast, { risk: (w.risks as Record<string, string>)[p.risk_at_least] }));
  if (p.resource_types?.length) parts.push(p.resource_types.join(", "));
  return parts.join(" · ");
}

export function PoliciesCard({ canManage, roles }: { canManage: boolean; roles: CustomRole[] }) {
  const t = useDictionary();
  const w = t.governance;
  const confirm = useConfirm();
  const { data } = usePolicies();
  const change = usePolicyChange();
  const [name, setName] = useState("");
  const [effect, setEffect] = useState<"deny" | "allow">("deny");
  const [action, setAction] = useState<string>("agent:run");
  const [risk, setRisk] = useState<"" | "low" | "medium" | "high" | "critical">("");
  const [who, setWho] = useState<Set<string>>(new Set());
  const [priority, setPriority] = useState("50");

  async function create(event: React.FormEvent) {
    event.preventDefault();
    const body: PolicyUpdate = {
      name: name.trim(),
      effect,
      actions: [action],
      roles: [...who],
      resource_types: risk ? ["capability"] : [],
      risk_at_least: risk || null,
      priority: Number(priority) || 0,
      enabled: true,
    };
    if (await said(t, change.createPolicy.mutateAsync(body), fill(w.policySaved, { name: body.name }))) {
      setName("");
      setWho(new Set());
    }
  }

  function toggle(p: Policy) {
    const body: PolicyUpdate = {
      name: p.name,
      description: p.description,
      effect: p.effect,
      actions: p.actions,
      roles: p.roles,
      resource_types: p.resource_types,
      risk_at_least: p.risk_at_least,
      kinds: p.kinds,
      categories: p.categories,
      priority: p.priority,
      enabled: !p.enabled,
    };
    void said(
      t,
      change.updatePolicy.mutateAsync({ id: p.id, body }),
      p.enabled ? w.policyOff : w.policyOn,
    );
  }

  async function remove(p: Policy) {
    const ok = await confirm({ title: fill(w.deletePolicyTitle, { name: p.name }), confirmLabel: w.delete, destructive: true });
    if (ok) await said(t, change.deletePolicy.mutateAsync(p.id), fill(w.policyDeleted, { name: p.name }));
  }

  const roleChoices = [
    { value: "member", label: w.roles.member },
    { value: "admin", label: w.roles.admin },
    ...roles.map((r) => ({ value: r.key, label: r.name })),
  ];

  return (
    <Card title={w.policies} icon={<Scale className="size-4 text-shell-muted" aria-hidden="true" />}>
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.policiesSaid}</p>
      {data?.length ? (
        <ul className="mb-4 flex flex-col gap-2" data-testid="policies">
          {data.map((p) => (
            <li key={p.id} data-policy={p.id} className="flex flex-wrap items-center gap-2 rounded-lg border border-shell-line p-3 text-[0.8125rem]">
              <Pill tone={p.effect === "deny" ? "danger" : "success"}>
                {p.effect === "deny" ? w.refuses : w.exception}
              </Pill>
              <span className="font-medium text-brand-navy">{p.name}</span>
              <span className="text-xs text-shell-muted">{fill(w.priority, { priority: p.priority })}</span>
              {!p.enabled ? <Pill tone="neutral">{w.off}</Pill> : null}
              <span className="w-full text-xs text-shell-muted">{policySaid(t, p)}</span>
              {canManage ? (
                <span className="flex gap-2">
                  <Button type="button" size="sm" variant="outline" onClick={() => toggle(p)}>
                    {p.enabled ? w.turnOff : w.turnOn}
                  </Button>
                  <Button type="button" size="sm" variant="outline" onClick={() => void remove(p)}>
                    {w.delete}
                  </Button>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-4 text-[0.8125rem] text-shell-muted">{w.noPolicy}</p>
      )}
      {canManage ? (
        <form className="flex flex-col gap-2" onSubmit={(e) => void create(e)} data-testid="policy-form">
          <label htmlFor="policy-name" className="text-[0.8125rem] font-medium text-brand-navy">
            {w.newPolicy}
          </label>
          <Input id="policy-name" placeholder={w.policyNamePlaceholder} value={name} onChange={(e) => setName(e.target.value)} />
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
              {w.effect}
              <select className="h-9 rounded-md border border-shell-line bg-white px-2 text-sm" value={effect} onChange={(e) => setEffect(e.target.value as "deny" | "allow")}>
                <option value="deny">{w.refuses}</option>
                <option value="allow">{w.exception}</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
              {w.action}
              <select className="h-9 rounded-md border border-shell-line bg-white px-2 text-sm" value={action} onChange={(e) => setAction(e.target.value)}>
                {ACTIONS.map((a) => (
                  <option key={a} value={a}>
                    {permissionSaid(t, a)}
                  </option>
                ))}
                <option value="intention:create">{permissionSaid(t, "intention:create")}</option>
                <option value="intention:approve">{permissionSaid(t, "intention:approve")}</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
              {w.riskLabel}
              <select className="h-9 rounded-md border border-shell-line bg-white px-2 text-sm" value={risk} onChange={(e) => setRisk(e.target.value as "" | "low" | "medium" | "high" | "critical")}>
                <option value="">{w.anyRisk}</option>
                <option value="medium">{fill(w.riskAtLeast, { risk: w.risks.medium })}</option>
                <option value="high">{fill(w.riskAtLeast, { risk: w.risks.high })}</option>
                <option value="critical">{fill(w.riskAtLeast, { risk: w.risks.critical })}</option>
              </select>
            </label>
            <label className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
              {w.priorityLabel}
              <Input type="number" min={0} max={100} value={priority} onChange={(e) => setPriority(e.target.value)} />
            </label>
          </div>
          <Checks id="policy-roles" label={w.appliesTo} options={roleChoices} chosen={who} onChange={setWho} />
          <div>
            <Button type="submit" disabled={name.trim().length < 2 || change.createPolicy.isPending}>
              {w.createPolicy}
            </Button>
          </div>
        </form>
      ) : null}
    </Card>
  );
}

function eventSaid(t: Dictionary, e: GovernanceEvent): string {
  const w = t.governance;
  const what = (w.subjects as Record<string, string>)[e.subject_type] ?? e.subject_type;
  const kind = (w.kinds as Record<string, string>)[e.kind] ?? e.kind;
  const name = (e.after?.name ?? e.before?.name ?? e.after?.role ?? "") as string;
  return `${what} ${kind}${name ? ` · ${name}` : ""}`;
}

export function HistoryCard() {
  const t = useDictionary();
  const { locale } = useLocale();
  const { data } = useGovernanceHistory();
  return (
    <Card title={t.governance.history} icon={<History className="size-4 text-shell-muted" aria-hidden="true" />}>
      {data?.length ? (
        <ol className="flex flex-col gap-1 text-[0.8125rem]" data-testid="governance-history">
          {data.map((e) => (
            <li key={e.id} className="text-brand-navy">
              {eventSaid(t, e)} <span className="text-xs text-shell-muted">· {exactDate(locale, e.at)}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-[0.8125rem] text-shell-muted">{t.governance.noHistory}</p>
      )}
    </Card>
  );
}
