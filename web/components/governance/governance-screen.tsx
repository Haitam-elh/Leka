"use client";

import { Clock, EyeOff, FileText, History, Lock, ShieldCheck, ShieldX, Users } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { cn } from "cn";

import { Card } from "@/components/environment/parts";
import { ApprovalGovernance } from "@/components/governance/approval-governance";
import { AgentUsageTab } from "@/components/governance/agent-usage";
import { DataProtection } from "@/components/governance/data-protection";
import { SecurityTab } from "@/components/governance/security-tab";
import { Pill } from "@/components/intelligence/pill";
import { useConfirm } from "@/components/interactions/confirm";
import { exactDate } from "@/components/knowledge/time";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { StatCard, StatGrid } from "@/components/shell/stat-card";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AccessDecision, AccessModel, EntityHit } from "@/lib/access";
import { AIAuditCard, AIControlsCard, ApprovalsCard } from "@/components/governance/ai-controls";
import { AuditLogCard, AuditRetentionCard } from "@/components/governance/audit-log";
import { FormDialog, HistoryCard, PoliciesCard, RolesCard } from "@/components/governance/roles-policies";
import {
  useAccessModel,
  useCustomRoles,
  useDecisions,
  useEntitySearch,
  usePolicies,
  useRestrictionChange,
  useRestrictions,
} from "@/lib/access-queries";
import { ApiError } from "@/lib/api";
import { fill, type Dictionary } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { buildBreadcrumb } from "@/lib/navigation/breadcrumb";
import { notify } from "@/lib/notify";
import { personName } from "@/lib/team";
import { useTeamMembers } from "@/lib/team-queries";
import { useAwaitingRuns } from "@/lib/ai-governance-queries";

/**
 * Sécurité & gouvernance (LEKA-402): who may do what — every role's
 * permissions, the reader's own marked — the entities only administrators
 * see, restricted saying why and lifted, and the trail of access decisions,
 * refusals first to hand; the controls on the workspace's AI, the runs
 * waiting for approval and what the controls did (LEKA-406). Every word is
 * the API's: the model the server enforces, not a copy of it. Its second tab,
 * Approbations, governs consequential actions (LEKA-404,
 * approval-governance.tsx); its third, Données, how data is protected
 * (LEKA-405, data-protection.tsx).
 */

const ROLE_ORDER = ["member", "admin", "owner"] as const;

export function permissionSaid(t: Dictionary, permission: string): string {
  return (t.governance.permissions as Record<string, string>)[permission] ?? permission;
}

function AccessMatrix({ model }: { model: AccessModel }) {
  const t = useDictionary();
  const w = t.governance;
  const granted = new Map(model.roles.map((r) => [r.role, new Set<string>(r.permissions)]));
  const writes = new Set<string>(model.writes);
  return (
    <Card title={w.matrix} icon={<ShieldCheck className="size-4 text-shell-muted" aria-hidden="true" />}>
      <p className="mb-3 text-[0.8125rem] text-shell-muted">
        {fill(w.yourRole, {
          role: model.custom_role ?? (w.roles as Record<string, string>)[model.role] ?? model.role,
        })}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-[0.8125rem]" data-testid="access-matrix">
          <thead>
            <tr className="text-start text-xs text-shell-muted">
              <th className="py-1 pe-3 font-medium">{w.permission}</th>
              {ROLE_ORDER.map((role) => (
                <th
                  key={role}
                  className={`px-2 py-1 text-center font-medium ${role === model.role ? "text-brand-navy" : ""}`}
                >
                  {(w.roles as Record<string, string>)[role]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {model.permissions.map((permission) => (
              <tr key={permission} className="border-t border-shell-line" data-permission={permission}>
                <td className="py-1.5 pe-3 text-brand-navy">
                  {permissionSaid(t, permission)}
                  {writes.has(permission) ? (
                    <span className="ms-2 text-xs text-shell-muted">{w.write}</span>
                  ) : null}
                </td>
                {ROLE_ORDER.map((role) => (
                  <td key={role} className="px-2 py-1.5 text-center">
                    {granted.get(role)?.has(permission) ? (
                      <span aria-label={w.yes}>✓</span>
                    ) : (
                      <span className="text-shell-muted" aria-label={w.no}>
                        —
                      </span>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Restrictions({ canRestrict }: { canRestrict: boolean }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.governance;
  const confirm = useConfirm();
  const { data } = useRestrictions();
  const { restrict, lift } = useRestrictionChange();
  const [q, setQ] = useState("");
  const [chosen, setChosen] = useState<EntityHit | null>(null);
  const [reason, setReason] = useState("");
  const [creating, setCreating] = useState(false);
  const found = useEntitySearch(chosen ? "" : q);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!chosen) return;
    try {
      await restrict.mutateAsync({ entityId: chosen.entity.id, reason: reason.trim() });
      notify.success({ title: fill(w.restricted, { name: chosen.entity.name }) });
      setChosen(null);
      setQ("");
      setReason("");
      setCreating(false);
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : w.failed });
    }
  }

  async function giveBack(entityId: string, name: string) {
    const ok = await confirm({
      title: fill(w.liftTitle, { name }),
      description: w.liftSaid,
      confirmLabel: w.lift,
    });
    if (!ok) return;
    try {
      await lift.mutateAsync(entityId);
      notify.success({ title: fill(w.lifted, { name }) });
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : w.failed });
    }
  }

  const form = (
    <form className="flex flex-col gap-2" onSubmit={(e) => void submit(e)} data-testid="restrict-form">
      <label htmlFor="restrict-search" className="text-[0.8125rem] font-medium text-brand-navy">
        {w.entity}
      </label>
      {chosen ? (
        <div className="flex flex-wrap items-center gap-2 text-[0.8125rem]">
          <Pill tone="violet">{chosen.entity.name}</Pill>
          <button type="button" className="text-xs text-shell-muted hover:underline" onClick={() => setChosen(null)}>
            {w.change}
          </button>
        </div>
      ) : (
        <>
          <Input
            id="restrict-search"
            placeholder={w.searchPlaceholder}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          {found.data?.entities.length ? (
            <ul className="flex flex-col gap-1" data-testid="restrict-results">
              {found.data.entities.slice(0, 6).map((hit) => (
                <li key={hit.entity.id}>
                  <button
                    type="button"
                    className="text-start text-[0.8125rem] text-brand-navy hover:underline"
                    onClick={() => setChosen(hit)}
                  >
                    {hit.entity.name} <span className="text-shell-muted">· {hit.entity.type}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}
      <label htmlFor="restrict-reason" className="text-[0.8125rem] font-medium text-brand-navy">
        {w.reason}
      </label>
      <Input
        id="restrict-reason"
        placeholder={w.reasonPlaceholder}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <div>
        <Button type="submit" disabled={!chosen || reason.trim().length < 3 || restrict.isPending}>
          <Lock className="size-4" aria-hidden="true" />
          {w.restrict}
        </Button>
      </div>
    </form>
  );

  return (
    <Card
      title={w.restrictions}
      icon={<EyeOff className="size-4 text-shell-muted" aria-hidden="true" />}
      action={
        canRestrict ? (
          <FormDialog label={w.restrictOne} open={creating} onOpenChange={setCreating}>
            {form}
          </FormDialog>
        ) : null
      }
    >
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.restrictionsSaid}</p>
      {data?.length ? (
        <ul className="mb-4 flex flex-col gap-2" data-testid="restrictions">
          {data.map((r) => (
            <li
              key={r.entity_id}
              data-entity={r.entity_id}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-shell-line p-3"
            >
              <Lock className="size-4 text-shell-muted" aria-hidden="true" />
              <span className="min-w-0 flex-1 text-[0.8125rem]">
                <span className="font-medium text-brand-navy">{r.name ?? w.gone}</span>
                <span className="text-shell-muted">
                  {" · "}
                  {r.reason} · {exactDate(locale, r.restricted_at)}
                </span>
              </span>
              {canRestrict ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void giveBack(r.entity_id, r.name ?? w.gone)}
                >
                  {w.lift}
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mb-4 text-[0.8125rem] text-shell-muted">{w.noRestriction}</p>
      )}
    </Card>
  );
}

function decisionSaid(t: Dictionary, d: AccessDecision): string {
  const w = t.governance;
  return (w.reasons as Record<string, string>)[d.reason] ?? d.reason;
}

function Decisions() {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.governance;
  const [only, setOnly] = useState<"deny" | null>("deny");
  const { data } = useDecisions(only);
  const members = useTeamMembers();
  const names = new Map((members.data ?? []).map((m) => [m.user_id, personName(m)]));
  return (
    <Card
      title={w.decisions}
      icon={<History className="size-4 text-shell-muted" aria-hidden="true" />}
      action={
        <div className="flex gap-1" role="group" aria-label={w.filter}>
          <Button
            type="button"
            size="sm"
            variant={only === "deny" ? "default" : "outline"}
            aria-pressed={only === "deny"}
            onClick={() => setOnly("deny")}
          >
            {w.refusals}
          </Button>
          <Button
            type="button"
            size="sm"
            variant={only === null ? "default" : "outline"}
            aria-pressed={only === null}
            onClick={() => setOnly(null)}
          >
            {w.all}
          </Button>
        </div>
      }
    >
      {!data?.length ? (
        <p className="text-[0.8125rem] text-shell-muted">{only === "deny" ? w.noRefusal : w.noDecision}</p>
      ) : (
        <ul className="flex flex-col gap-2" data-testid="decisions">
          {data.map((d) => (
            <li key={d.id} className="flex flex-col gap-0.5 border-t border-shell-line pt-2 text-[0.8125rem]" data-decision={d.decision}>
              <span className="flex flex-wrap items-center gap-2">
                <Pill tone={d.decision === "deny" ? "danger" : "success"}>
                  {d.decision === "deny" ? w.denied : w.allowed}
                </Pill>
                <span className="text-brand-navy">
                  {permissionSaid(t, d.action)}
                </span>
                {d.resource_type ? (
                  <span className="text-shell-muted">
                    · {(w.resources as Record<string, string>)[d.resource_type] ?? d.resource_type}
                    {d.resource_id ? ` ${d.resource_id.slice(0, 40)}` : ""}
                  </span>
                ) : null}
              </span>
              <span className="text-xs text-shell-muted">
                {(d.user_id && names.get(d.user_id)) || w.someone} ·{" "}
                {(w.roles as Record<string, string>)[d.role] ?? d.role} · {decisionSaid(t, d)} ·{" "}
                {exactDate(locale, d.at)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const TABS = ["overview", "access", "ai", "journal", "approvals", "security", "agents", "data"] as const;
type Tab = (typeof TABS)[number];

function tabHref(pathname: string, tab: Tab): string {
  return tab === "overview" ? pathname : `${pathname}?tab=${tab}`;
}

function useTab(): [Tab, (next: Tab) => void] {
  const router = useRouter();
  const pathname = usePathname() ?? "/governance";
  const asked = useSearchParams()?.get("tab");
  const tab: Tab = (TABS as readonly string[]).includes(asked ?? "") ? (asked as Tab) : "overview";
  return [tab, (next) => router.replace(tabHref(pathname, next), { scroll: false })];
}

const WEEK = 7 * 24 * 3600 * 1000;

/** What is true of the workspace's governance now, each figure opening what
 * it counts (LEKA-438) — no score: nothing computes one. */
function Overview({ mine }: { mine: Set<string> }) {
  const pathname = usePathname() ?? "/governance";
  const t = useDictionary();
  const w = t.governance.overview;
  const reads = mine.has("access:read");
  const roles = useCustomRoles();
  const policies = usePolicies();
  const awaiting = useAwaitingRuns();
  const restrictions = useRestrictions();
  const refusals = useDecisions("deny");
  // The trail sends its latest 100: a full page this week is "100+", not 100.
  const lately = (refusals.data ?? []).filter((d) => Date.now() - new Date(d.at).getTime() < WEEK).length;
  const count = (n: number | undefined, more = false) => (n === undefined ? "…" : `${n}${more ? "+" : ""}`);
  const tiles = [
    reads && {
      key: "refusals",
      icon: ShieldX,
      tone: "danger" as const,
      value: count(refusals.data && lately, lately >= 100),
      label: w.refusals,
      tab: null,
    },
    { key: "roles", icon: Users, tone: "violet" as const, value: count(roles.data?.length), label: w.roles, tab: "access" as const },
    { key: "policies", icon: FileText, tone: "info" as const, value: count(policies.data?.length), label: w.policies, tab: "access" as const },
    reads && {
      key: "restricted",
      icon: EyeOff,
      tone: "neutral" as const,
      value: count(restrictions.data?.length),
      label: w.restricted,
      tab: "access" as const,
    },
    { key: "awaiting", icon: Clock, tone: "warning" as const, value: count(awaiting.data?.length), label: w.awaiting, tab: "ai" as const },
  ].filter((tile) => !!tile);
  return (
    <div className="flex flex-col gap-4" data-testid="governance-overview">
      <StatGrid count={tiles.length}>
        {tiles.map((tile) => (
          <StatCard
            key={tile.key}
            icon={tile.icon}
            tone={tile.tone}
            value={tile.value}
            label={tile.label}
            href={tile.tab ? tabHref(pathname, tile.tab) : undefined}
            testId={`governance-stat-${tile.key}`}
          />
        ))}
      </StatGrid>
      {reads ? (
        <div className="grid gap-4 xl:grid-cols-2">
          <Decisions />
          <HistoryCard />
        </div>
      ) : null}
    </div>
  );
}

export function GovernanceScreen() {
  const t = useDictionary();
  const pathname = usePathname() ?? "/governance";
  const crumbs = buildBreadcrumb(pathname, t);
  const model = useAccessModel();
  const roles = useCustomRoles();
  const mine = new Set<string>(model.data?.mine ?? []);
  const [tab, setTab] = useTab();
  // The journal and the agents' use are for who may read the audit trail.
  const tabs = TABS.filter((name) => (name !== "journal" && name !== "agents") || mine.has("audit:read"));
  const manage = mine.has("policy:manage");

  let body: React.ReactNode;
  if (tab === "approvals") {
    body = <ApprovalGovernance />;
  } else if (tab === "data") {
    body = <DataProtection />;
  } else if (tab === "security") {
    // Devices, LEKA's access to each source, what LEKA keeps (2026-10-25).
    body = <SecurityTab canManageSources={mine.has("source:manage")} />;
  } else if (tab === "agents" && mine.has("audit:read")) {
    // Each agent's use, counted, and who ran which (2026-10-25).
    body = <AgentUsageTab />;
  } else if (model.isError) {
    body = <ErrorState error={model.error} onRetry={() => void model.refetch()} />;
  } else if (!model.data) {
    body = <div className="h-96 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  } else if (tab === "access") {
    body = (
      <div className="grid gap-4 xl:grid-cols-2">
        <div className="flex flex-col gap-4">
          <AccessMatrix model={model.data} />
        </div>
        <div className="flex flex-col gap-4">
          {/* Roles and policies of the workspace's own (LEKA-403). */}
          <RolesCard model={model.data} canManage={manage} />
          <PoliciesCard canManage={manage} roles={roles.data ?? []} />
          {mine.has("access:read") ? <Restrictions canRestrict={mine.has("entity:restrict")} /> : null}
        </div>
      </div>
    );
  } else if (tab === "ai") {
    // The workspace's AI, governed (LEKA-406).
    body = (
      <div className="grid gap-4 xl:grid-cols-2">
        <AIControlsCard canManage={manage} roles={roles.data ?? []} />
        <div className="flex flex-col gap-4">
          <ApprovalsCard canApprove={mine.has("intention:approve")} />
          {mine.has("access:read") ? <AIAuditCard /> : null}
        </div>
      </div>
    );
  } else if (tab === "journal" && mine.has("audit:read")) {
    // The audit trail (LEKA-407): everything that matters, searched.
    body = (
      <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <AuditLogCard />
        <AuditRetentionCard canChange={mine.has("audit:manage")} />
      </div>
    );
  } else {
    body = <Overview mine={mine} />;
  }
  return (
    <PageContainer>
      <PageHeader title={t.nav.governance} breadcrumb={crumbs} />
      <div className="mb-4 flex gap-1 overflow-x-auto border-b border-shell-line" role="tablist">
        {tabs.map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={tab === name}
            onClick={() => setTab(name)}
            data-testid={`governance-tab-${name}`}
            className={cn(
              "-mb-px shrink-0 border-b-2 px-3 py-2 text-[0.875rem] font-medium",
              tab === name
                ? "border-shell-nav-active text-shell-nav-active"
                : "border-transparent text-shell-muted hover:text-brand-navy",
            )}
          >
            {name === "data" ? t.protection.tab : t.decisions.governance.tabs[name]}
          </button>
        ))}
      </div>
      {body}
    </PageContainer>
  );
}
