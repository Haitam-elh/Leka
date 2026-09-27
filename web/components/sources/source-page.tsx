"use client";

import { HeartPulse, Pencil, Plug, Power, PowerOff, RefreshCw, Trash2 } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import { useConfirm } from "@/components/interactions/confirm";
import { MetadataPanel, type MetadataItem } from "@/components/knowledge/metadata-panel";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { RouteState } from "@/components/shell/route-state";
import { useCurrentUser, usePermissions } from "@/components/shell/shell-provider";
import { AddSourceDialog } from "@/components/sources/add-source-dialog";
import { SourceFacts, SourceHistory } from "@/components/sources/source-panel";
import { SourceLogo } from "@/components/sources/source-logo";
import { SourceRunsSection } from "@/components/sources/source-runs";
import { SourceSettingsSection } from "@/components/sources/source-settings";
import { SourceSyncSection } from "@/components/sources/source-sync";
import { ErrorState } from "@/components/states/error-state";
import { LoadingState } from "@/components/states/loading-state";
import { Button } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { ApiError } from "@/lib/api";
import { buildBreadcrumb } from "@/lib/navigation/breadcrumb";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import { canActivate, canDisable, canSync, type Source, sources, sourceTone } from "@/lib/sources";
import { scopeFieldOf } from "@/lib/sources-form";
import { useCatalog, useSource, useSourceMutation, useSyncSummaries } from "@/lib/sources-queries";

/**
 * One source, with everything that can be done to it (LEKA-345).
 *
 * What it is, where it stands and its last error with what to do about it
 * (the same blocks as the list's panel), its configuration and scope, and
 * its whole history. An admin can test it, check its health, switch it on
 * or off, change it through the wizard, or delete it — typing its name
 * first, because its credentials go with it.
 *
 * A member sees all of it and none of the buttons: the API would refuse
 * them (source:manage), and a button that can only fail is not offered.
 */
export function SourcePage({ sourceId }: { sourceId: string }) {
  const t = useDictionary();
  const pathname = usePathname() ?? routes.source(sourceId);
  const query = useSource(sourceId);

  if (query.isPending) return <LoadingState size="page" />;
  if (query.error instanceof ApiError && query.error.status === 404) {
    return (
      <PageContainer>
        <RouteState variant="not-found" />
      </PageContainer>
    );
  }
  if (query.isError) {
    return (
      <PageContainer>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} size="page" />
      </PageContainer>
    );
  }

  const source = query.data;
  const crumbs = buildBreadcrumb(pathname, t).map((crumb, index, all) =>
    index === all.length - 1 ? { ...crumb, label: source.display_name } : crumb,
  );
  return (
    <PageContainer>
      <PageHeader
        title={source.display_name}
        breadcrumb={crumbs}
        actions={<Actions source={source} />}
      />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="flex flex-col gap-4">
          <section className="flex flex-col gap-4 rounded-xl border border-shell-line bg-white p-4">
            <div className="flex items-center gap-3">
              <SourceLogo kind={source.type} className="size-8" />
              <StatusBadge variant={`source.${sourceTone(source)}`} />
            </div>
            <Facts source={source} />
          </section>
          <SourceSyncSection source={source} />
          <SourceRunsSection source={source} />
          <Configuration source={source} />
          <SourceSettingsSection source={source} />
        </div>
        <section className="self-start rounded-xl border border-shell-line bg-white p-4">
          <h2 className="mb-3 text-lg font-semibold text-brand-navy">{t.sources.page.history}</h2>
          <SourceHistory source={source} limit={50} />
        </section>
      </div>
    </PageContainer>
  );
}

function Facts({ source }: { source: Source }) {
  const summaries = useSyncSummaries();
  return (
    <SourceFacts
      source={source}
      owner={useOwner(source)}
      records={summaries.data?.get(source.id)?.records_total}
    />
  );
}

function useOwner(source: Source): string {
  const t = useDictionary();
  const me = useCurrentUser();
  if (source.created_by === null) return "—";
  return source.created_by === me?.id ? t.sources.owner.you : t.sources.owner.member;
}

// ── What it is set to ───────────────────────────────────────────────────────

function Configuration({ source }: { source: Source }) {
  const t = useDictionary();
  const catalog = useCatalog();
  const entry = catalog.data?.find((e) => e.key === source.type);
  const scopeField = entry ? scopeFieldOf(entry.config_schema) : null;
  const known = t.sources.fields as Record<string, { label: string }>;

  const items: MetadataItem[] = Object.entries(source.config)
    .filter(([key]) => key !== scopeField)
    .map(([key, value]) => ({
      label: known[key]?.label ?? key,
      value: value === null || value === "" ? t.sources.page.defaultValue : String(value),
    }));
  const scope = scopeField ? source.config[scopeField] : undefined;
  if (scopeField) {
    items.push({
      label: t.sources.page.scope,
      value: Array.isArray(scope) ? (scope as string[]).join(", ") : t.sources.page.scopeAll,
    });
  }

  return (
    <section className="rounded-xl border border-shell-line bg-white p-4">
      {entry || !catalog.data ? null : (
        <p className="mb-3 text-sm text-shell-muted">{t.sources.page.noConnector}</p>
      )}
      <MetadataPanel sections={[{ title: t.sources.page.configuration, items }]} />
    </section>
  );
}

// ── What can be done to it ──────────────────────────────────────────────────

function Actions({ source }: { source: Source }) {
  const t = useDictionary();
  const p = t.sources.page;
  const router = useRouter();
  const confirm = useConfirm();
  const catalog = useCatalog();
  const canManage = usePermissions()?.includes("source:manage") ?? false;
  const [editing, setEditing] = useState(false);
  const run = useSourceMutation(async (action: () => Promise<unknown>) => action());

  if (!canManage) return null;
  const hasConnector = catalog.data?.some((e) => e.key === source.type) ?? false;
  const name = source.display_name;

  async function attempt(action: () => Promise<unknown>, done: () => void) {
    try {
      await run.mutateAsync(action);
      done();
    } catch (caught) {
      const refused = caught instanceof ApiError && caught.status === 409;
      notify.error({ title: refused ? p.activateRefused : p.actionFailed });
    }
  }

  async function test() {
    await attempt(
      async () => {
        const outcome = await sources.test(source.id);
        if (outcome.ok) notify.success({ title: p.testOk });
        else
          notify.error({
            title: p.testFailed,
            description: outcome.diagnostic
              ? `${outcome.diagnostic.message} ${outcome.diagnostic.remediation}`
              : undefined,
          });
      },
      () => {},
    );
  }

  async function syncNow() {
    await attempt(
      async () => {
        const { queued } = await sources.syncNow(source.id);
        if (queued) {
          notify.info({
            title: t.sources.sync.started,
            description: fill(t.sources.sync.startedBody, { name }),
          });
        } else {
          notify.info({ title: fill(t.sources.sync.already, { name }) });
        }
      },
      () => {},
    );
  }

  async function checkHealth() {
    await attempt(
      () => sources.checkHealth(source.id),
      () => {},
    );
  }

  async function remove() {
    const sure = await confirm({
      title: fill(p.deleteTitle, { name }),
      description: p.deleteBody,
      confirmLabel: p.deleteConfirm,
      destructive: true,
      requireTypedConfirmation: name,
    });
    if (!sure) return;
    await attempt(
      () => sources.remove(source.id),
      () => {
        notify.success({ title: fill(p.deleted, { name }) });
        router.push(routes.sources());
      },
    );
  }

  const busy = run.isPending;
  return (
    <div className="flex flex-wrap gap-2">
      {hasConnector ? (
        <>
          {canSync(source) ? (
            <Button onClick={() => void syncNow()} disabled={busy}>
              <RefreshCw aria-hidden="true" />
              {t.sources.sync.now}
            </Button>
          ) : null}
          <Button variant="outline" onClick={() => void test()} disabled={busy}>
            <Plug aria-hidden="true" />
            {p.test}
          </Button>
          <Button variant="outline" onClick={() => void checkHealth()} disabled={busy}>
            <HeartPulse aria-hidden="true" />
            {p.health}
          </Button>
          <Button variant="outline" onClick={() => setEditing(true)} disabled={busy}>
            <Pencil aria-hidden="true" />
            {p.edit}
          </Button>
        </>
      ) : null}
      {canActivate(source) && hasConnector ? (
        <Button
          onClick={() =>
            void attempt(
              () => sources.activate(source.id),
              () => notify.success({ title: fill(p.activated, { name }) }),
            )
          }
          disabled={busy}
        >
          <Power aria-hidden="true" />
          {p.activate}
        </Button>
      ) : null}
      {canDisable(source) ? (
        <Button
          variant="outline"
          onClick={() =>
            void attempt(
              () => sources.disable(source.id),
              () => notify.info({ title: fill(p.disabled, { name }) }),
            )
          }
          disabled={busy}
        >
          <PowerOff aria-hidden="true" />
          {p.disable}
        </Button>
      ) : null}
      <Button variant="destructive" onClick={() => void remove()} disabled={busy}>
        <Trash2 aria-hidden="true" />
        {p.delete}
      </Button>
      {editing ? (
        <AddSourceDialog
          open
          editing={source}
          onOpenChange={setEditing}
          onDone={() => setEditing(false)}
        />
      ) : null}
    </div>
  );
}
