"use client";

import { KeyRound, Laptop, LogOut, ShieldCheck } from "lucide-react";

import { Card } from "@/components/environment/parts";
import { useConfirm } from "@/components/interactions/confirm";
import { exactDate, timeAgo } from "@/components/knowledge/time";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import { type DeviceSession } from "@/lib/security";
import { useDeviceSessions, useRevokeSource, useSignOutDevice } from "@/lib/security-queries";
import { useSources } from "@/lib/sources-queries";

/**
 * Sécurité & gouvernance › Sessions et accès (2026-10-25): the devices
 * signed in to one's account, each signed out in a click; LEKA's access to
 * each source, revoked by who manages sources — its credentials erased,
 * what it read kept; and what LEKA keeps, said plainly.
 */

/** A browser and its system, as a person recognises them. */
export function deviceOf(agent: string | null | undefined): string | null {
  if (!agent) return null;
  const browser = /Edg\//.test(agent)
    ? "Edge"
    : /Firefox\//.test(agent)
      ? "Firefox"
      : /Chrome\//.test(agent)
        ? "Chrome"
        : /Safari\//.test(agent)
          ? "Safari"
          : null;
  const system = /iPhone|iPad/.test(agent)
    ? "iOS"
    : /Android/.test(agent)
      ? "Android"
      : /Mac OS X|Macintosh/.test(agent)
        ? "macOS"
        : /Windows/.test(agent)
          ? "Windows"
          : /Linux/.test(agent)
            ? "Linux"
            : null;
  const said = [browser, system].filter(Boolean).join(" · ");
  return said || null;
}

function Devices() {
  const t = useDictionary();
  const w = t.security.sessions;
  const { format: locale } = useLocale();
  const sessions = useDeviceSessions();
  const signOut = useSignOutDevice();
  const others = (sessions.data ?? []).filter((s) => !s.is_current);

  async function out(ids: string[]) {
    try {
      for (const id of ids) await signOut.mutateAsync(id);
      notify.success({ title: w.signedOut });
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : String(error) });
    }
  }

  function line(session: DeviceSession) {
    return (
      <li
        key={session.id}
        className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-shell-line py-2 last:border-0"
        data-testid="device-session"
        data-current={session.is_current || undefined}
      >
        <Laptop className="size-4 shrink-0 text-shell-muted" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="text-[0.8125rem] font-medium text-brand-navy">
            {deviceOf(session.user_agent) ?? w.unknownDevice}
            {session.is_current ? (
              <span className="ml-2 rounded-full bg-state-success-soft px-2 py-0.5 text-xs text-state-success">
                {w.current}
              </span>
            ) : null}
          </p>
          <p className="text-xs text-shell-muted">
            {fill(w.seen, { when: timeAgo(t, session.last_seen_at).toLocaleLowerCase(locale) })}
            {" · "}
            {fill(w.since, { date: exactDate(locale, session.created_at) })}
            {session.ip_prefix ? ` · ${fill(w.from, { ip: session.ip_prefix })}` : ""}
          </p>
        </div>
        {!session.is_current ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={signOut.isPending}
            onClick={() => void out([session.id])}
            data-testid="device-sign-out"
          >
            <LogOut className="size-3.5" aria-hidden="true" />
            {w.signOut}
          </Button>
        ) : null}
      </li>
    );
  }

  return (
    <Card
      title={w.title}
      icon={<Laptop className="size-4 text-shell-muted" aria-hidden="true" />}
      action={
        others.length > 1 ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={signOut.isPending}
            onClick={() => void out(others.map((s) => s.id))}
            data-testid="device-sign-out-others"
          >
            {w.signOutOthers}
          </Button>
        ) : null
      }
    >
      <p className="mb-2 text-[0.8125rem] text-shell-muted">{w.intro}</p>
      <ul data-testid="device-sessions">{(sessions.data ?? []).map(line)}</ul>
      {sessions.data && !others.length ? <p className="text-xs text-shell-muted">{w.none}</p> : null}
    </Card>
  );
}

function SourceAccess({ canManage }: { canManage: boolean }) {
  const t = useDictionary();
  const w = t.security.sources;
  const confirm = useConfirm();
  const sources = useSources();
  const revoke = useRevokeSource();
  const listed = sources.data ?? [];

  async function ask(id: string, name: string) {
    const ok = await confirm({
      title: fill(w.confirmTitle, { name }),
      description: w.confirmBody,
      confirmLabel: w.confirm,
    });
    if (!ok) return;
    try {
      await revoke.mutateAsync(id);
      notify.success({ title: w.revoked });
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : String(error) });
    }
  }

  return (
    <Card title={w.title} icon={<KeyRound className="size-4 text-shell-muted" aria-hidden="true" />}>
      <p className="mb-2 text-[0.8125rem] text-shell-muted">{w.intro}</p>
      {listed.length ? (
        <ul data-testid="source-access">
          {listed.map((source) => {
            const hint = source.credentials?.hint ?? null;
            return (
              <li
                key={source.id}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-shell-line py-2 last:border-0"
                data-testid="source-access-line"
                data-status={source.status}
              >
                <div className="min-w-0 flex-1">
                  <p className="text-[0.8125rem] font-medium text-brand-navy">{source.display_name}</p>
                  <p className="text-xs text-shell-muted">
                    {hint ? fill(w.credentials, { hint }) : w.noCredentials}
                  </p>
                </div>
                {canManage && hint ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={revoke.isPending}
                    onClick={() => void ask(source.id, source.display_name)}
                    data-testid="source-revoke"
                  >
                    {w.revoke}
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-xs text-shell-muted">{w.none}</p>
      )}
      {!canManage && listed.length ? <p className="mt-2 text-xs text-shell-muted">{w.managersOnly}</p> : null}
    </Card>
  );
}

function Stored() {
  const t = useDictionary();
  const w = t.security.stored;
  return (
    <Card title={w.title} icon={<ShieldCheck className="size-4 text-shell-muted" aria-hidden="true" />}>
      <ul className="flex list-disc flex-col gap-1.5 pl-5 text-[0.8125rem] text-brand-navy" data-testid="security-stored">
        {w.items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-shell-muted">{w.more}</p>
    </Card>
  );
}

export function SecurityTab({ canManageSources }: { canManageSources: boolean }) {
  return (
    <div className="grid gap-4 xl:grid-cols-2" data-testid="security-tab">
      <div className="flex flex-col gap-4">
        <Devices />
        <Stored />
      </div>
      <SourceAccess canManage={canManageSources} />
    </div>
  );
}
