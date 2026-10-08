"use client";

import { Copy, KeyRound, Plus, Trash2, Webhook } from "lucide-react";
import { useState } from "react";

import { Card } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { useConfirm } from "@/components/interactions/confirm";
import { timeAgo } from "@/components/knowledge/time";
import { usePermissions } from "@/components/shell/shell-provider";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import type { ActionEndpoint } from "@/lib/actions";
import { useEndpointChange, useEndpoints } from "@/lib/actions-queries";
import { ApiError } from "@/lib/api";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

/**
 * Paramètres → Actions autorisées (LEKA-391): the systems LEKA may act
 * through — the workspace's own automation behind an https address, each
 * with the actions and environments it accepts. Made, its signing secret
 * is shown once, to copy; then each can be disabled, enabled, removed.
 * Without one, every approved action is a person's to do and confirm.
 * Admins only change them; anyone may read them.
 */

const FIELD =
  "rounded-md border border-shell-line bg-white px-2 py-1.5 text-sm text-brand-navy outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40";

function list(said: string): string[] {
  return said
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function NewEndpoint({ onMade }: { onMade: (secret: string) => void }) {
  const t = useDictionary();
  const w = t.actionEndpoints;
  const { create } = useEndpointChange();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("https://");
  const [actions, setActions] = useState("restart, rollback");
  const [environments, setEnvironments] = useState("production");
  return (
    <form
      className="flex flex-col gap-3 rounded-lg border border-brand-violet/40 bg-brand-violet-soft/30 p-3"
      data-testid="endpoint-form"
      onSubmit={async (event) => {
        event.preventDefault();
        try {
          const made = await create.mutateAsync({
            name: name.trim(),
            url: url.trim(),
            actions: list(actions),
            environments: list(environments),
            targets: [],
          });
          onMade(made.secret);
        } catch (error) {
          notify.error({ title: error instanceof ApiError ? error.message : String(error) });
        }
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-shell-nav">{w.name}</span>
          <input
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            className={FIELD}
            data-testid="endpoint-name"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-shell-nav">{w.url}</span>
          <input
            required
            type="url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            className={FIELD}
            data-testid="endpoint-url"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-shell-nav">
            {w.actions} <span className="text-shell-muted">({w.hint})</span>
          </span>
          <input
            required
            value={actions}
            onChange={(event) => setActions(event.target.value)}
            className={FIELD}
            data-testid="endpoint-actions"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-shell-nav">
            {w.environments} <span className="text-shell-muted">({w.hint})</span>
          </span>
          <input
            required
            value={environments}
            onChange={(event) => setEnvironments(event.target.value)}
            className={FIELD}
            data-testid="endpoint-environments"
          />
        </label>
      </div>
      <div>
        <Button type="submit" size="sm" disabled={create.isPending} data-testid="endpoint-create">
          {w.create}
        </Button>
      </div>
    </form>
  );
}

/** Made: its secret, this once. */
function Secret({ secret, onClose }: { secret: string; onClose: () => void }) {
  const t = useDictionary();
  const w = t.actionEndpoints;
  const [copied, setCopied] = useState(false);
  return (
    <div
      className="flex flex-col gap-2 rounded-lg border border-state-warning/40 bg-state-warning-soft/40 p-3 text-sm"
      data-testid="endpoint-secret"
    >
      <p className="flex items-center gap-2 font-semibold text-brand-navy">
        <KeyRound className="size-4" aria-hidden="true" />
        {w.secretTitle}
      </p>
      <p className="text-shell-muted">{w.secretBody}</p>
      <code className="rounded bg-white px-2 py-1 font-mono text-xs break-all text-brand-navy select-all">
        {secret}
      </code>
      <p className="text-xs text-shell-muted">{w.verify}</p>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(secret);
              setCopied(true);
            } catch {
              setCopied(false);
            }
          }}
        >
          <Copy className="size-4" aria-hidden="true" />
          {copied ? w.copied : w.copy}
        </Button>
        <Button type="button" size="sm" onClick={onClose} data-testid="endpoint-secret-close">
          {w.close}
        </Button>
      </div>
    </div>
  );
}

function EndpointLine({ endpoint, admin }: { endpoint: ActionEndpoint; admin: boolean }) {
  const t = useDictionary();
  const w = t.actionEndpoints;
  const confirm = useConfirm();
  const { update, remove } = useEndpointChange();
  return (
    <li
      className="flex flex-wrap items-start gap-3 py-3"
      data-testid="endpoint"
      data-enabled={endpoint.enabled ? "true" : "false"}
    >
      <Webhook className="mt-0.5 size-4 shrink-0 text-shell-nav-active" aria-hidden="true" />
      <div className="min-w-0 flex-1 text-sm">
        <p className="font-semibold text-brand-navy">{endpoint.name}</p>
        <p className="truncate text-xs text-shell-muted">{endpoint.url}</p>
        <p className="mt-1 flex flex-wrap gap-1.5">
          {endpoint.actions.map((action) => (
            <Pill key={action} tone="violet">
              {(t.intentions.understanding.actionNames as Record<string, string>)[action] ?? action}
            </Pill>
          ))}
          {endpoint.environments.map((environment) => (
            <Pill key={environment} tone="neutral">
              {environment}
            </Pill>
          ))}
        </p>
        <p className="mt-1 text-xs text-shell-muted">
          {endpoint.last_called_at
            ? fill(w.lastCalled, { when: timeAgo(t, endpoint.last_called_at) })
            : w.never}
        </p>
      </div>
      <Pill tone={endpoint.enabled ? "success" : "neutral"}>
        {endpoint.enabled ? w.enabled : w.disabled}
      </Pill>
      {admin ? (
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={update.isPending}
            onClick={() =>
              void update.mutateAsync({ id: endpoint.id, body: { enabled: !endpoint.enabled } })
            }
            data-testid="endpoint-toggle"
          >
            {endpoint.enabled ? w.disable : w.enable}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            aria-label={`${w.remove} ${endpoint.name}`}
            disabled={remove.isPending}
            onClick={async () => {
              const yes = await confirm({
                title: w.removeTitle,
                description: w.removeBody,
                confirmLabel: w.remove,
                destructive: true,
              });
              if (yes) {
                await remove.mutateAsync(endpoint.id);
                notify.success({ title: w.done });
              }
            }}
          >
            <Trash2 className="size-4" aria-hidden="true" />
          </Button>
        </div>
      ) : null}
    </li>
  );
}

export function ActionEndpoints() {
  const t = useDictionary();
  const w = t.actionEndpoints;
  const admin = usePermissions()?.includes("workspace:update") ?? false;
  const found = useEndpoints();
  const [adding, setAdding] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  return (
    <Card
      title={w.title}
      icon={<Webhook className="size-4 text-shell-muted" aria-hidden="true" />}
      action={
        admin && !adding && !secret ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setAdding(true)}
            data-testid="endpoint-add"
          >
            <Plus className="size-4" aria-hidden="true" />
            {w.add}
          </Button>
        ) : undefined
      }
    >
      <div className="flex flex-col gap-3" data-testid="action-endpoints">
        <p className="text-[0.8125rem] text-shell-muted">{w.body}</p>
        {secret ? <Secret secret={secret} onClose={() => setSecret(null)} /> : null}
        {adding ? (
          <NewEndpoint
            onMade={(made) => {
              setAdding(false);
              setSecret(made);
            }}
          />
        ) : null}
        {found.isError ? (
          <ErrorState error={found.error} onRetry={() => void found.refetch()} />
        ) : found.data?.length ? (
          <ul className="divide-y divide-shell-line/60">
            {found.data.map((endpoint) => (
              <EndpointLine key={endpoint.id} endpoint={endpoint} admin={admin} />
            ))}
          </ul>
        ) : found.data ? (
          <p className="text-[0.8125rem] text-brand-navy">{w.empty}</p>
        ) : null}
        {!admin ? <p className="text-xs text-shell-muted">{w.readOnly}</p> : null}
      </div>
    </Card>
  );
}
