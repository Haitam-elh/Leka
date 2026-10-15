"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { PageContainer } from "@/components/shell/page-container";
import { useShell, useShellRetry } from "@/components/shell/shell-provider";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { routes } from "@/config/routes";
import type { WorkspaceMembership } from "@/lib/auth";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { workspace } from "@/lib/workspace";

/**
 * What someone signed in sees while no workspace is open.
 *
 * A new account belongs to none: every page asks for a permission that
 * only a workspace gives, so the shell used to show an empty sidebar and a
 * refusal — a person who had just registered from leka-core.com found no
 * way in and no connectors. Now they create their workspace, its name
 * taken from the company they gave at registration, and are asked which
 * of their tools to connect (components/sources/welcome-page.tsx).
 *
 * Someone with workspaces but none open (a session from before they were
 * let in) is offered those instead.
 *
 * POST /workspaces is the API's own: the one tenancy action someone who is
 * in no workspace may take. It makes them the owner.
 */
export function WorkspaceGate({ children }: { children: React.ReactNode }) {
  const shell = useShell();
  if (shell.status !== "ready" || shell.workspace !== null) return <>{children}</>;

  return (
    <PageContainer>
      <div className="mx-auto max-w-lg py-10">
        {shell.me.workspaces.length > 0 ? (
          <OpenOne memberships={shell.me.workspaces} />
        ) : (
          <CreateOne company={shell.me.user.company ?? ""} />
        )}
      </div>
    </PageContainer>
  );
}

function CreateOne({ company }: { company: string }) {
  const t = useDictionary();
  const router = useRouter();
  const retry = useShellRetry();
  const [name, setName] = useState(company);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFailed(false);
    try {
      const created = await workspace.create(name.trim());
      await workspace.enter(created.id);
      // Where a new workspace has something to do: connecting its tools.
      router.push(routes.welcome());
      retry();
    } catch {
      setFailed(true);
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-shell-line bg-white p-6">
      <h1 className="text-xl font-semibold text-brand-navy">{t.shell.firstWorkspace.title}</h1>
      <p className="mt-2 text-sm text-shell-muted">{t.shell.firstWorkspace.body}</p>
      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        {failed ? (
          <Alert variant="destructive">
            <AlertDescription>{t.shell.firstWorkspace.failed}</AlertDescription>
          </Alert>
        ) : null}
        <div className="space-y-2">
          <Label htmlFor="workspace-name">{t.shell.firstWorkspace.name}</Label>
          <Input
            id="workspace-name"
            required
            maxLength={200}
            autoComplete="organization"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <Button type="submit" className="w-full" disabled={busy || name.trim() === ""}>
          {busy ? t.shell.firstWorkspace.creating : t.shell.firstWorkspace.create}
        </Button>
      </form>
    </section>
  );
}

function OpenOne({ memberships }: { memberships: readonly WorkspaceMembership[] }) {
  const t = useDictionary();
  const router = useRouter();
  const retry = useShellRetry();
  const [busy, setBusy] = useState<string | null>(null);

  async function open(id: string) {
    setBusy(id);
    try {
      await workspace.enter(id);
      router.push(routes.overview());
      retry();
    } catch {
      setBusy(null);
    }
  }

  return (
    <section className="rounded-xl border border-shell-line bg-white p-6">
      <h1 className="text-xl font-semibold text-brand-navy">{t.shell.firstWorkspace.yours}</h1>
      <ul className="mt-4 space-y-2">
        {/* One's own first; a demonstration last (LEKA-449). */}
        {[...memberships].sort((a, b) => Number(!!a.demo) - Number(!!b.demo)).map((membership) => (
          <li key={membership.id} className="flex items-center justify-between gap-4">
            <span className="truncate text-sm font-medium text-shell-nav">{membership.name}</span>
            <Button
              size="sm"
              disabled={busy !== null}
              onClick={() => void open(membership.id)}
            >
              {t.shell.firstWorkspace.open}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}
