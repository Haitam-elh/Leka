"use client";

import { Activity, Building2, Plug, Trash2 } from "lucide-react";
import { useState } from "react";

import { Card } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { useConfirm } from "@/components/interactions/confirm";
import { usePermissions } from "@/components/shell/shell-provider";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { type ModelSettings, type WorkspaceModelUpdate } from "@/lib/models";
import { useModelChange, useModelSettings } from "@/lib/models-queries";
import { notify } from "@/lib/notify";

/**
 * Paramètres → Le modèle de votre entreprise (LEKA-394): under an Enterprise
 * contract that brings it (LEKA-530), the company plugs in its own model —
 * its Azure OpenAI, its Mistral, OpenAI, Anthropic or Google account —
 * tested, removed, or made the only one. A model plugged in before it was
 * the contract's is said, still answers, and can be removed. Never LEKA's
 * models, their prices or what they used: the LEKA team assigns a model to
 * each agent, and reads that internally. Admins change it; anyone reads it.
 * A key is never shown again: its last four characters are.
 */

const FIELD =
  "rounded-md border border-shell-line bg-white px-2 py-1.5 text-sm text-brand-navy outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40";

type Provider = WorkspaceModelUpdate["provider"];

function OwnForm({ gateway, onDone }: { gateway: ModelSettings; onDone: () => void }) {
  const t = useDictionary();
  const w = t.companyModel;
  const { save } = useModelChange();
  const own = gateway.own;
  const [provider, setProvider] = useState<Provider>(
    (own?.provider as Provider | undefined) ?? "azure_openai",
  );
  const [model, setModel] = useState(own?.model ?? "");
  const [baseUrl, setBaseUrl] = useState(own?.base_url ?? "");
  const [apiVersion, setApiVersion] = useState(own?.api_version ?? "");
  const [apiKey, setApiKey] = useState("");
  const [enabled, setEnabled] = useState(own?.enabled ?? true);
  const [exclusive, setExclusive] = useState(own?.exclusive ?? false);
  const needs = gateway.providers.find((p) => p.name === provider)?.needs ?? [];
  const azure = provider === "azure_openai";
  const keyKept = own?.key_hint && own.provider === provider;
  return (
    <form
      className="flex flex-col gap-3 rounded-lg border border-brand-violet/40 bg-brand-violet-soft/30 p-3"
      data-testid="model-form"
      onSubmit={async (event) => {
        event.preventDefault();
        try {
          await save.mutateAsync({
            provider,
            model: model.trim() || null,
            base_url: baseUrl.trim() || null,
            api_version: apiVersion.trim() || null,
            api_key: apiKey.trim() || null,
            enabled,
            exclusive,
          });
          notify.success({ title: w.saved });
          onDone();
        } catch (error) {
          notify.error({ title: error instanceof ApiError ? error.message : String(error) });
        }
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-shell-nav">{w.provider}</span>
          <select
            value={provider}
            onChange={(event) => setProvider(event.target.value as Provider)}
            className={FIELD}
            data-testid="model-provider"
          >
            {gateway.providers.map((p) => (
              <option key={p.name} value={p.name}>
                {p.title}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-shell-nav">{azure ? w.deployment : w.model}</span>
          <input
            required={needs.includes("model")}
            value={model}
            placeholder={gateway.providers.find((p) => p.name === provider)?.default_model ?? ""}
            onChange={(event) => setModel(event.target.value)}
            className={FIELD}
            data-testid="model-name"
          />
        </label>
        {needs.includes("url") || provider === "openai" ? (
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-shell-nav">{w.baseUrl}</span>
            <input
              required={needs.includes("url")}
              type="url"
              value={baseUrl}
              placeholder={azure ? "https://votre-ressource.openai.azure.com" : "https://"}
              onChange={(event) => setBaseUrl(event.target.value)}
              className={FIELD}
              data-testid="model-url"
            />
          </label>
        ) : null}
        {azure ? (
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-shell-nav">{w.apiVersion}</span>
            <input
              value={apiVersion}
              placeholder="2024-10-21"
              onChange={(event) => setApiVersion(event.target.value)}
              className={FIELD}
              data-testid="model-version"
            />
          </label>
        ) : null}
        <label className="flex flex-col gap-1 text-sm sm:col-span-2">
          <span className="text-shell-nav">{w.apiKey}</span>
          <input
            type="password"
            autoComplete="off"
            required={!keyKept}
            value={apiKey}
            placeholder={keyKept ? fill(w.keyKept, { hint: own?.key_hint ?? "" }) : ""}
            onChange={(event) => setApiKey(event.target.value)}
            className={FIELD}
            data-testid="model-key"
          />
        </label>
      </div>
      <label className="flex items-center gap-2 text-sm text-brand-navy">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        {w.enabled}
      </label>
      <label className="flex items-center gap-2 text-sm text-brand-navy">
        <input
          type="checkbox"
          checked={exclusive}
          onChange={(event) => setExclusive(event.target.checked)}
          data-testid="model-exclusive"
        />
        {w.exclusive}
      </label>
      <div>
        <Button type="submit" size="sm" disabled={save.isPending} data-testid="model-save">
          {w.save}
        </Button>
      </div>
    </form>
  );
}

function OwnModel({ gateway, admin }: { gateway: ModelSettings; admin: boolean }) {
  const t = useDictionary();
  const w = t.companyModel;
  const confirm = useConfirm();
  const { test, remove } = useModelChange();
  const [editing, setEditing] = useState(false);
  const own = gateway.own;
  const vendor = own ? gateway.providers.find((p) => p.name === own.provider) : undefined;
  const tone = own?.status === "ok" ? "success" : own?.status === "failed" ? "danger" : "neutral";
  return (
    <div className="flex flex-col gap-2" data-testid="model-own">
      <p className="text-[0.8125rem] text-shell-muted" data-testid="model-own-body">
        {gateway.offered ? w.body : w.legacy}
      </p>
      {own ? (
        <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="model-own-line">
          <span className="font-medium text-brand-navy">{vendor?.title ?? own.provider}</span>
          {own.model ? <span className="text-shell-muted">· {own.model}</span> : null}
          {own.key_hint ? <span className="text-xs text-shell-muted">…{own.key_hint}</span> : null}
          <Pill tone={tone}>{w.statuses[own.status]}</Pill>
          {own.exclusive ? <Pill tone="violet">{w.exclusiveOn}</Pill> : null}
          {own.status_detail ? (
            <span className="w-full text-xs text-state-danger">{own.status_detail}</span>
          ) : null}
        </div>
      ) : (
        <p className="text-[0.8125rem] text-brand-navy">{w.none}</p>
      )}
      {admin ? (
        <div className="flex flex-wrap gap-2">
          {/* A model of its own is brought under the contract only. */}
          {!editing && gateway.offered ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setEditing(true)}
              data-testid="model-bring"
            >
              <Plug className="size-4" aria-hidden="true" />
              {own ? w.edit : w.bring}
            </Button>
          ) : null}
          {own ? (
            <>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={test.isPending}
                data-testid="model-test"
                onClick={async () => {
                  const tested = await test.mutateAsync();
                  if (tested.ok) {
                    notify.success({
                      title: fill(w.tested, {
                        ms: String(tested.latency_ms ?? 0),
                        version: tested.version ?? tested.model ?? "",
                      }),
                    });
                  } else {
                    notify.error({ title: fill(w.testFailed, { detail: tested.detail ?? "" }) });
                  }
                }}
              >
                <Activity className="size-4" aria-hidden="true" />
                {test.isPending ? w.testing : w.test}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                aria-label={w.remove}
                disabled={remove.isPending}
                data-testid="model-remove"
                onClick={async () => {
                  const yes = await confirm({
                    title: w.removeTitle,
                    description: w.removeBody,
                    confirmLabel: w.remove,
                    destructive: true,
                  });
                  if (yes) {
                    await remove.mutateAsync();
                    notify.success({ title: w.removed });
                  }
                }}
              >
                <Trash2 className="size-4" aria-hidden="true" />
              </Button>
            </>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-shell-muted">{w.readOnly}</p>
      )}
      {editing ? <OwnForm gateway={gateway} onDone={() => setEditing(false)} /> : null}
    </div>
  );
}

export function CompanyModel() {
  const t = useDictionary();
  const w = t.companyModel;
  const admin = usePermissions()?.includes("workspace:update") ?? false;
  const settings = useModelSettings();
  // A public plan without one: nothing to show, nothing to choose.
  if (settings.data && !settings.data.offered && !settings.data.own) return null;
  if (!settings.data && !settings.isError) return null;
  return (
    <Card title={w.title} icon={<Building2 className="size-4 text-shell-muted" aria-hidden="true" />}>
      <div className="flex flex-col gap-4" data-testid="company-model">
        {settings.isError ? (
          <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />
        ) : settings.data ? (
          <OwnModel gateway={settings.data} admin={admin} />
        ) : null}
      </div>
    </Card>
  );
}
