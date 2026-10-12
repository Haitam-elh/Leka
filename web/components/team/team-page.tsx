"use client";

import {
  Clock,
  KeyRound,
  Mail,
  Plus,
  Search,
  ShieldCheck,
  Timer,
  UserCheck,
  Users,
  UsersRound,
} from "lucide-react";
import { usePathname } from "next/navigation";
import { useMemo, useState } from "react";

import { cn } from "cn";

import { Pill } from "@/components/intelligence/pill";
import { useConfirm } from "@/components/interactions/confirm";
import { exactDate, timeAgo } from "@/components/knowledge/time";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { StatCard, StatGrid } from "@/components/shell/stat-card";
import { useCurrentUser, usePermissions } from "@/components/shell/shell-provider";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { useEnvironment } from "@/lib/environment-queries";
import { fill } from "@/lib/i18n/dictionaries";
import { buildBreadcrumb } from "@/lib/navigation/breadcrumb";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import { initials, personName, type Role, ROLES, type TeamMember } from "@/lib/team";
import { useInvitations, useTeamChange, useTeamMembers } from "@/lib/team-queries";

/**
 * Équipe & accès, as docs/product/mockups/15-equipe-acces.jpeg: who is in
 * the workspace — name, address, role, last sign-in — who is invited and
 * until when; inviting (emailed, the link also shown), changing a role,
 * removing a seat, revoking an invitation, for who may. Every figure real;
 * the teams are the company model's. The security settings say what LEKA
 * does, nothing it does not.
 */

const FIELD =
  "h-9 rounded-md border border-shell-line bg-white px-2 text-sm text-brand-navy outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40";
const ROLE_TONE: Record<Role, "violet" | "info" | "neutral"> = {
  owner: "violet",
  admin: "info",
  member: "neutral",
};

function Invite({ onClose }: { onClose: () => void }) {
  const t = useDictionary();
  const w = t.team;
  const { invite } = useTeamChange();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [link, setLink] = useState<string | null>(null);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    try {
      const made = await invite.mutateAsync({ email: email.trim(), role });
      notify.success({ title: fill(w.sent, { email: email.trim() }) });
      setLink(`${window.location.origin}/invitations/${encodeURIComponent(made.token)}`);
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : String(error) });
    }
  }

  return (
    <section className="rounded-xl border border-shell-line bg-white p-4" data-testid="team-invite">
      <h2 className="font-semibold text-brand-navy">{w.inviteTitle}</h2>
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.inviteBody}</p>
      <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => void send(event)}>
        <label className="flex min-w-60 flex-1 flex-col gap-1 text-xs text-shell-nav">
          {w.email}
          <input
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className={FIELD}
            data-testid="invite-email"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-shell-nav">
          {w.role}
          <select
            value={role}
            onChange={(event) => setRole(event.target.value as Role)}
            className={FIELD}
            data-testid="invite-role"
          >
            {(["member", "admin", "owner"] as const).map((name) => (
              <option key={name} value={name}>
                {w.roles[name]}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" disabled={invite.isPending || !email.trim()} data-testid="invite-send">
          <Mail className="size-4" aria-hidden="true" />
          {w.send}
        </Button>
        <Button type="button" variant="ghost" onClick={onClose}>
          {w.cancel}
        </Button>
      </form>
      {link ? (
        <div className="mt-3 rounded-lg bg-shell-canvas p-3 text-xs" data-testid="invite-link">
          <p className="text-shell-muted">{w.link}</p>
          <p className="mt-1 font-mono break-all text-brand-navy select-all">{link}</p>
        </div>
      ) : null}
    </section>
  );
}

function Members({ members, canManage }: { members: TeamMember[]; canManage: boolean }) {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const me = useCurrentUser();
  const w = t.team;
  const confirm = useConfirm();
  const { changeRole, remove } = useTeamChange();
  const [q, setQ] = useState("");
  const shown = useMemo(() => {
    const words = q.trim().toLowerCase();
    return words
      ? members.filter((m) => `${personName(m)} ${m.email}`.toLowerCase().includes(words))
      : members;
  }, [members, q]);

  async function role(member: TeamMember, next: Role) {
    try {
      await changeRole.mutateAsync({ id: member.id, role: next });
      notify.success({ title: w.roleChanged });
    } catch (error) {
      notify.error({
        title:
          error instanceof ApiError && error.status === 409
            ? w.lastOwner
            : error instanceof ApiError
              ? error.message
              : String(error),
      });
    }
  }

  async function drop(member: TeamMember) {
    const yes = await confirm({
      title: w.removeTitle,
      description: w.removeBody,
      confirmLabel: w.remove,
      destructive: true,
      impact: [`${personName(member)} · ${member.email}`],
    });
    if (!yes) return;
    try {
      await remove.mutateAsync(member.id);
      notify.success({ title: w.removed });
    } catch (error) {
      notify.error({
        title:
          error instanceof ApiError && error.status === 409
            ? w.lastOwner
            : error instanceof ApiError
              ? error.message
              : String(error),
      });
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <label className="relative flex max-w-72 items-center">
        <Search className="absolute start-2.5 size-4 text-shell-muted" aria-hidden="true" />
        <input
          value={q}
          onChange={(event) => setQ(event.target.value)}
          placeholder={w.search}
          aria-label={w.search}
          className={cn(FIELD, "w-full ps-8")}
          data-testid="team-search"
        />
      </label>
      <div className="overflow-x-auto">
        <table className="w-full text-start text-[0.8125rem]" data-testid="team-members">
          <thead className="text-xs text-shell-muted">
            <tr className="border-b border-shell-line">
              <th className="py-2 font-medium">{w.columns.name}</th>
              <th className="py-2 font-medium">{w.columns.role}</th>
              <th className="py-2 font-medium">{w.columns.status}</th>
              <th className="py-2 font-medium">{w.columns.lastLogin}</th>
              <th className="py-2 font-medium">{w.columns.joined}</th>
              {canManage ? <th className="py-2 font-medium">{w.columns.actions}</th> : null}
            </tr>
          </thead>
          <tbody>
            {shown.map((member) => {
              const mine = member.user_id === me?.id;
              return (
                <tr key={member.id} className="border-b border-shell-line/60" data-testid="team-member">
                  <td className="py-2.5">
                    <div className="flex items-center gap-2.5">
                      <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-violet-soft text-xs font-semibold text-shell-nav-active">
                        {initials(member)}
                      </span>
                      <div className="min-w-0">
                        <p className="truncate font-medium text-brand-navy">
                          {personName(member)}
                          {mine ? <span className="font-normal text-shell-muted"> ({w.you})</span> : null}
                        </p>
                        <p className="truncate text-xs text-shell-muted">{member.email}</p>
                      </div>
                    </div>
                  </td>
                  <td className="py-2.5">
                    {canManage && !mine ? (
                      <select
                        value={member.role}
                        onChange={(event) => void role(member, event.target.value as Role)}
                        className={FIELD}
                        aria-label={`${w.columns.role} · ${personName(member)}`}
                        data-testid="team-role"
                      >
                        {ROLES.map((name) => (
                          <option key={name} value={name}>
                            {w.roles[name]}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <Pill tone={ROLE_TONE[member.role]}>{w.roles[member.role]}</Pill>
                    )}
                  </td>
                  <td className="py-2.5">
                    <Pill tone="success" dot>
                      {w.active}
                    </Pill>
                  </td>
                  <td className="py-2.5 text-shell-muted">
                    {member.last_login_at ? timeAgo(t, member.last_login_at) : w.never}
                  </td>
                  <td className="py-2.5 text-shell-muted">{exactDate(locale, member.joined_at)}</td>
                  {canManage ? (
                    <td className="py-2.5">
                      {mine ? null : (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="border-state-danger/40 text-state-danger hover:bg-state-danger-soft"
                          onClick={() => void drop(member)}
                          data-testid="team-remove"
                        >
                          {w.remove}
                        </Button>
                      )}
                    </td>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Invitations() {
  const t = useDictionary();
  const { format: locale } = useLocale();
  const w = t.team;
  const invitations = useInvitations(true);
  const { revoke } = useTeamChange();
  if (!invitations.data) {
    return <div className="h-32 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  }
  if (!invitations.data.length) {
    return <p className="py-6 text-center text-[0.8125rem] text-shell-muted">{w.invitationsEmpty}</p>;
  }
  return (
    <ul className="divide-y divide-shell-line/60" data-testid="team-invitations">
      {invitations.data.map((invitation) => (
        <li key={invitation.id} className="flex flex-wrap items-center gap-3 py-2.5 text-[0.8125rem]" data-testid="team-invitation">
          <Mail className="size-4 text-shell-muted" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium text-brand-navy">{invitation.email}</p>
            <p className="text-xs text-shell-muted">
              {w.roles[invitation.role]}
              {invitation.invited_by ? ` · ${fill(w.invitedBy, { name: invitation.invited_by })}` : ""}
              {` · ${fill(w.expires, { when: exactDate(locale, invitation.expires_at) })}`}
            </p>
          </div>
          <Pill tone={invitation.expired ? "neutral" : "warning"} dot>
            {invitation.expired ? w.expired : w.pending}
          </Pill>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={revoke.isPending}
            onClick={() =>
              void revoke.mutateAsync(invitation.id).then(() => notify.success({ title: w.revoked }))
            }
            data-testid="team-revoke"
          >
            {w.revoke}
          </Button>
        </li>
      ))}
    </ul>
  );
}

export function TeamScreen() {
  const t = useDictionary();
  const pathname = usePathname();
  const w = t.team;
  const permissions = usePermissions() ?? [];
  const canInvite = permissions.includes("member:invite");
  const canManage = permissions.includes("member:update_role");
  const members = useTeamMembers();
  const invitations = useInvitations(canInvite);
  const environment = useEnvironment();
  const [tab, setTab] = useState<"members" | "invitations">("members");
  const [inviting, setInviting] = useState(false);
  const teams = environment.data?.nodes.filter((node) => node.type === "team").length;
  const byRole = ROLES.map((role) => ({
    role,
    count: members.data?.filter((m) => m.role === role).length ?? 0,
  }));
  const total = members.data?.length ?? 0;

  const tiles = [
    { key: "members", icon: Users, tone: "violet" as const, value: members.data ? String(total) : "…", label: w.stats.members, foot: null },
    { key: "roles", icon: ShieldCheck, tone: "success" as const, value: "3", label: w.stats.roles, foot: w.stats.rolesFoot },
    { key: "teams", icon: UsersRound, tone: "violet" as const, value: teams === undefined ? "…" : String(teams), label: w.stats.teams, foot: w.stats.teamsFoot },
    {
      key: "invitations",
      icon: Clock,
      tone: "warning" as const,
      value: canInvite ? (invitations.data ? String(invitations.data.filter((i) => !i.expired).length) : "…") : "—",
      label: w.stats.invitations,
      foot: w.stats.invitationsFoot,
    },
  ];

  return (
    <PageContainer>
      <PageHeader
        title={w.title}
        subtitle={w.subtitle}
        breadcrumb={buildBreadcrumb(pathname, t)}
        actions={
          canInvite ? (
            <Button type="button" onClick={() => setInviting(true)} data-testid="team-invite-open">
              <Plus className="size-4" aria-hidden="true" />
              {w.invite}
            </Button>
          ) : null
        }
      />

      <div className="flex flex-col gap-4">
        <StatGrid count={tiles.length} testId="team-stats">
          {tiles.map((tile) => (
            <StatCard
              key={tile.key}
              icon={tile.icon}
              tone={tile.tone}
              value={tile.value}
              label={tile.label}
              foot={tile.foot}
              testId={`team-stat-${tile.key}`}
            />
          ))}
        </StatGrid>

        {inviting ? <Invite onClose={() => setInviting(false)} /> : null}

        <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <section className="rounded-xl border border-shell-line bg-white p-4">
            <div className="mb-3 flex gap-1 border-b border-shell-line" role="tablist">
              {(["members", ...(canInvite ? (["invitations"] as const) : [])] as const).map((name) => (
                <button
                  key={name}
                  type="button"
                  role="tab"
                  aria-selected={tab === name}
                  onClick={() => setTab(name)}
                  data-testid={`team-tab-${name}`}
                  className={cn(
                    "-mb-px border-b-2 px-3 py-2 text-[0.875rem] font-medium",
                    tab === name
                      ? "border-shell-nav-active text-shell-nav-active"
                      : "border-transparent text-shell-muted hover:text-brand-navy",
                  )}
                >
                  {w.tabs[name]}
                  {name === "members" && members.data ? ` ${total}` : ""}
                  {name === "invitations" && invitations.data ? ` ${invitations.data.length}` : ""}
                </button>
              ))}
            </div>
            {tab === "invitations" ? (
              <Invitations />
            ) : members.isError ? (
              <ErrorState error={members.error} onRetry={() => void members.refetch()} />
            ) : members.data ? (
              <Members members={members.data} canManage={canManage} />
            ) : (
              <div className="h-48 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />
            )}
            {!canManage ? <p className="mt-3 text-xs text-shell-muted">{w.readOnly}</p> : null}
          </section>

          <div className="flex flex-col gap-4">
            <section className="rounded-xl border border-shell-line bg-white p-4" data-testid="team-split">
              <h2 className="mb-3 font-semibold text-brand-navy">{w.split}</h2>
              <ul className="space-y-2.5">
                {byRole.map(({ role, count }) => (
                  <li key={role} className="text-[0.8125rem]">
                    <div className="mb-1 flex justify-between">
                      <span className="text-brand-navy">{w.roles[role]}</span>
                      <span className="text-shell-muted tabular-nums">{count}</span>
                    </div>
                    <div className="h-2 rounded-full bg-shell-canvas">
                      <div
                        className="h-2 rounded-full bg-shell-nav-active"
                        style={{ width: `${total ? (count / total) * 100 : 0}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            </section>
            <section className="rounded-xl border border-shell-line bg-white p-4" data-testid="team-security">
              <h2 className="mb-3 font-semibold text-brand-navy">{w.security}</h2>
              <ul className="space-y-2.5 text-[0.8125rem]">
                {(
                  [
                    [UserCheck, w.securityItems.verified],
                    [KeyRound, w.securityItems.password],
                    [Timer, w.securityItems.sessions],
                    [ShieldCheck, w.securityItems.roles],
                  ] as const
                ).map(([Icon, line]) => (
                  <li key={line} className="flex items-start gap-2 text-brand-navy">
                    <Icon className="mt-0.5 size-4 shrink-0 text-state-success" aria-hidden="true" />
                    {line}
                  </li>
                ))}
              </ul>
            </section>
          </div>
        </div>

        <section className="flex flex-wrap items-center gap-4 rounded-xl bg-brand-violet-soft/60 px-5 py-4">
          <ShieldCheck className="size-6 shrink-0 text-shell-nav-active" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <p className="font-semibold text-brand-navy">{w.bannerTitle}</p>
            <p className="text-[0.8125rem] text-shell-muted">{w.bannerBody}</p>
          </div>
        </section>
      </div>
    </PageContainer>
  );
}
