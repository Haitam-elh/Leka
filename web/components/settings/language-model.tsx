"use client";

import { Activity, Building2, Cpu, Plug, Trash2 } from "lucide-react";
import { useState } from "react";

import { Card } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { useConfirm } from "@/components/interactions/confirm";
import { timeAgo } from "@/components/knowledge/time";
import { usePermissions } from "@/components/shell/shell-provider";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import {
  cents,
  dollars,
  type ModelGateway,
  type ModelProfile,
  type ModelUsage,
  type WorkspaceModelUpdate,
} from "@/lib/models";
import { useModelChange, useModelGateway, useModelUsage } from "@/lib/models-queries";
import { notify } from "@/lib/notify";

/**
 * Paramètres → Modèle de langage (LEKA-394): the model that reads what is
 * asked and writes LEKA's answers. LEKA's by default — Gemini 3.8 Flash,
 * its price, what answers when it does not; the company's own if it plugs
 * one in — its Azure OpenAI, its Mistral, OpenAI, Anthropic or Google
 * account — tested, removed, or made the only one; what was asked of models
 * over 30 days, and what it cost at list price. Admins change it; anyone
 * reads it. A key is never shown again: its last four characters are.
 */

const FIELD =
  "rounded-md border border-shell-line bg-white px-2 py-1.5 text-sm text-brand-navy outline-none focus-visible:ring-2 focus-visible:ring-brand-violet/40";

type Provider = WorkspaceModelUpdate["provider"];

function number(value: number, locale: string): string {
  return new Intl.NumberFormat(locale === "fr" ? "fr-FR" : "en-GB").format(value);
}

function priceSaid(t: Dictionary, profile: ModelProfile, locale: string): string[] {
  const w = t.languageModel;
  const where = locale === "fr" ? "fr-FR" : "en-GB";
  if (!profile.price) return [w.noPrice];
  const said = [
    fill(w.price, {
      in: dollars(profile.price.per_million_in, where),
      out: dollars(profile.price.per_million_out, where),
    }),
  ];
  if (profile.next_price) {
    said.push(
      fill(w.nextPrice, {
        in: dollars(profile.next_price.per_million_in, where),
        out: dollars(profile.next_price.per_million_out, where),
        since: new Date(profile.next_price.since).toLocaleDateString(where),
      }),
    );
  }
  return said;
}

function DefaultModel({ gateway }: { gateway: ModelGateway }) {
  const t = useDictionary();
  const w = t.languageModel;
  const { locale } = useLocale();
  const model = gateway.default;
  const vendor = gateway.providers.find((p) => p.name === model.provider);
  return (
    <div className="flex flex-col gap-1.5 rounded-lg bg-shell-canvas p-3" data-testid="model-default">
      <p className="text-xs font-semibold tracking-[0.04em] text-shell-muted uppercase">
        {w.defaultTitle}
      </p>
      <p className="flex flex-wrap items-center gap-2">
        <Cpu className="size-4 text-shell-nav-active" aria-hidden="true" />
        <span className="font-semibold text-brand-navy">{model.title}</span>
        <span className="text-sm text-shell-muted">· {vendor?.title ?? model.provider}</span>
        <Pill tone={gateway.default_ready ? "success" : "warning"}>
          {gateway.default_ready ? w.ready : w.notReady}
        </Pill>
      </p>
      {priceSaid(t, model, locale).map((line) => (
        <p key={line} className="text-[0.8125rem] text-brand-navy">
          {line}
        </p>
      ))}
      <p className="text-xs text-shell-muted">
        {fill(w.context, { tokens: number(model.context, locale) })}
        {" · "}
        {gateway.fallbacks.length
          ? fill(w.fallbacks, { models: gateway.fallbacks.map((f) => f.title).join(", ") })
          : w.noFallback}
      </p>
    </div>
  );
}

function Answering({ gateway }: { gateway: ModelGateway }) {
  const t = useDictionary();
  const w = t.languageModel;
  return (
    <div className="flex flex-col gap-1.5">
      <p className="text-sm font-semibold text-brand-navy">{w.answering}</p>
      {gateway.answering.length ? (
        <ol className="flex flex-col gap-1" data-testid="model-answering">
          {gateway.answering.map((route, index) => (
            <li
              key={`${route.owner}:${route.provider}:${route.model}`}
              className="flex flex-wrap items-center gap-2 text-[0.8125rem] text-brand-navy"
            >
              <span className="w-4 text-shell-muted tabular-nums">{index + 1}.</span>
              <span className="font-medium">{route.title}</span>
              <Pill tone={route.owner === "workspace" ? "violet" : "neutral"}>
                {w.owners[route.owner]}
              </Pill>
              <span className="text-xs text-shell-muted">{w.why[route.why]}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-[0.8125rem] text-brand-navy" data-testid="model-nobody">
          {w.nobody}
        </p>
      )}
    </div>
  );
}

function OwnForm({ gateway, onDone }: { gateway: ModelGateway; onDone: () => void }) {
  const t = useDictionary();
  const w = t.languageModel;
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

function OwnModel({ gateway, admin }: { gateway: ModelGateway; admin: boolean }) {
  const t = useDictionary();
  const w = t.languageModel;
  const confirm = useConfirm();
  const { test, remove } = useModelChange();
  const [editing, setEditing] = useState(false);
  const own = gateway.own;
  const vendor = own ? gateway.providers.find((p) => p.name === own.provider) : undefined;
  const tone = own?.status === "ok" ? "success" : own?.status === "failed" ? "danger" : "neutral";
  return (
    <div className="flex flex-col gap-2" data-testid="model-own">
      <p className="flex items-center gap-2 text-sm font-semibold text-brand-navy">
        <Building2 className="size-4 text-shell-muted" aria-hidden="true" />
        {w.ownTitle}
      </p>
      <p className="text-[0.8125rem] text-shell-muted">{w.ownBody}</p>
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
        <p className="text-[0.8125rem] text-brand-navy">{w.ownNone}</p>
      )}
      {admin ? (
        <div className="flex flex-wrap gap-2">
          {!editing ? (
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

function Usage({ usage }: { usage: ModelUsage }) {
  const t = useDictionary();
  const w = t.languageModel;
  const { locale } = useLocale();
  const where = locale === "fr" ? "fr-FR" : "en-GB";
  const total = usage.total;
  const purposes = w.purposes as Record<string, string>;
  const tiles = [
    { key: "calls", label: w.calls, value: number(total.calls, locale) },
    { key: "failed", label: w.failed, value: number(total.failed, locale) },
    { key: "tokens", label: w.tokens, value: number(total.tokens_in + total.tokens_out, locale) },
    { key: "cost", label: w.cost, value: dollars(total.cost_usd, where) },
  ];
  return (
    <div className="flex flex-col gap-2" data-testid="model-usage">
      <p className="text-sm font-semibold text-brand-navy">{w.usageTitle}</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {tiles.map((tile) => (
          <div
            key={tile.key}
            className="rounded-lg bg-shell-canvas px-3 py-2"
            data-testid={`model-usage-${tile.key}`}
          >
            <p className="text-xs text-shell-muted">{tile.label}</p>
            <p className="text-lg font-semibold text-brand-navy tabular-nums">{tile.value}</p>
          </div>
        ))}
      </div>
      {total.calls ? (
        <>
          <p className="text-xs text-shell-muted">
            {fill(w.split, {
              leka: number(usage.leka.calls, locale),
              own: number(usage.own.calls, locale),
            })}
            {usage.fallbacks ? ` · ${fill(w.fallbacksUsed, { count: String(usage.fallbacks) })}` : ""}
          </p>
          {usage.per_intention_usd ? (
            <p className="text-xs text-brand-navy" data-testid="model-per-intention">
              {fill(w.perIntention, {
                cost: cents(usage.per_intention_usd, where),
                count: number(usage.intentions ?? 0, locale),
                many: number(Math.floor(10 / usage.per_intention_usd), locale),
              })}
            </p>
          ) : null}
          {total.tokens_cached ? (
            <p className="text-xs text-shell-muted" data-testid="model-cached">
              {fill(w.cached, {
                share: String(Math.round((total.tokens_cached / Math.max(total.tokens_in, 1)) * 100)),
              })}
            </p>
          ) : null}
          {total.unpriced ? (
            <p className="text-xs text-shell-muted">
              {fill(w.costNote, { unpriced: String(total.unpriced) })}
            </p>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <p className="mb-1 text-xs font-semibold text-shell-nav">{w.byModel}</p>
              <ul className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
                {usage.by_model.map((m) => (
                  <li key={`${m.provider}:${m.model}`} className="flex justify-between gap-2">
                    <span>{m.title}</span>
                    <span className="text-shell-muted tabular-nums">
                      {number(m.tally.calls, locale)} · {dollars(m.tally.cost_usd, where)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="mb-1 text-xs font-semibold text-shell-nav">{w.byPurpose}</p>
              <ul className="flex flex-col gap-1 text-[0.8125rem] text-brand-navy">
                {usage.by_purpose.map((p) => (
                  <li key={p.purpose} className="flex justify-between gap-2">
                    <span>{purposes[p.purpose] ?? p.purpose}</span>
                    <span className="text-shell-muted tabular-nums">
                      {number(p.tally.calls, locale)} · {dollars(p.tally.cost_usd, where)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
          {Object.keys(usage.runs).length ? (
            <p className="text-xs text-shell-muted" data-testid="model-runs">
              <span className="font-semibold text-shell-nav">{w.runsTitle} : </span>
              {(["succeeded", "invalid", "no_model", "timed_out", "failed"] as const)
                .filter((status) => usage.runs[status])
                .map((status) => `${usage.runs[status]} ${w.runStatuses[status]}`)
                .join(" · ")}
            </p>
          ) : null}
          <div>
            <p className="mb-1 text-xs font-semibold text-shell-nav">{w.latest}</p>
            <ul className="divide-y divide-shell-line/60 text-[0.8125rem]">
              {usage.latest.slice(0, 6).map((call) => (
                <li
                  key={call.id}
                  className="flex flex-wrap items-center gap-2 py-1.5"
                  data-testid="model-call"
                >
                  <span className="text-brand-navy">{purposes[call.purpose] ?? call.purpose}</span>
                  <span className="text-shell-muted">· {call.version ?? call.model}</span>
                  <Pill tone={call.status === "ok" ? "success" : "danger"}>
                    {w.callStatuses[call.status]}
                  </Pill>
                  <span className="ml-auto text-xs text-shell-muted tabular-nums">
                    {number(call.tokens_in + call.tokens_out, locale)} tokens ·{" "}
                    {timeAgo(t, call.at)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </>
      ) : (
        <p className="text-[0.8125rem] text-shell-muted">{w.none}</p>
      )}
    </div>
  );
}

export function LanguageModel() {
  const t = useDictionary();
  const w = t.languageModel;
  const admin = usePermissions()?.includes("workspace:update") ?? false;
  const gateway = useModelGateway();
  const usage = useModelUsage(30);
  return (
    <Card title={w.title} icon={<Cpu className="size-4 text-shell-muted" aria-hidden="true" />}>
      <div className="flex flex-col gap-4" data-testid="language-model">
        <p className="text-[0.8125rem] text-shell-muted">{w.body}</p>
        {gateway.isError ? (
          <ErrorState error={gateway.error} onRetry={() => void gateway.refetch()} />
        ) : gateway.data ? (
          <>
            <DefaultModel gateway={gateway.data} />
            <Answering gateway={gateway.data} />
            <OwnModel gateway={gateway.data} admin={admin} />
            {usage.data ? <Usage usage={usage.data} /> : null}
          </>
        ) : null}
      </div>
    </Card>
  );
}
