"use client";

import { ArrowRight, TriangleAlert, X } from "lucide-react";
import Link from "next/link";

import { EventTimeline, type TimelineEvent } from "@/components/knowledge/event-timeline";
import { MetadataPanel, type MetadataItem } from "@/components/knowledge/metadata-panel";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { exactDate, timeAgo } from "@/components/knowledge/time";
import { SourceLogo, sourceTitle } from "@/components/sources/source-logo";
import { Tabs, TabsList, TabsPanel, TabsTab } from "@/components/ui/tabs";
import { routes } from "@/config/routes";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { type Diagnostic, type Source, type SourceEvent, sourceTone } from "@/lib/sources";
import { useSourceEvents } from "@/lib/sources-queries";

/**
 * One source, beside the list — the right-hand panel of mockup 12.
 *
 * Details: what it is, where it stands, what it reads, its credentials (the
 * hint only — the API never returns more) and, when something failed, the
 * diagnostic in the admin's words with what to do about it. History: its
 * events, newest first. The tabs "Éléments" and "Intégrations" of the
 * mockup wait for what fills them: the sync engine (LEKA-352).
 */
export function SourcePanel({
  source,
  owner,
  records,
  onClose,
}: {
  source: Source;
  owner: string;
  records?: number;
  onClose: () => void;
}) {
  const t = useDictionary();
  const s = t.sources.panel;
  return (
    <aside
      aria-label={fill(s.label, { name: source.display_name })}
      className="flex flex-col gap-4 self-start rounded-xl border border-shell-line bg-white p-4 xl:sticky xl:top-4"
    >
      <header className="flex items-center gap-3">
        <SourceLogo kind={source.type} className="size-8 shrink-0" />
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-lg font-semibold text-brand-navy">{source.display_name}</h2>
          <StatusBadge variant={`source.${sourceTone(source)}`} size="sm" />
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={s.close}
          className="rounded p-1 text-shell-muted outline-none hover:text-brand-navy focus-visible:ring-2 focus-visible:ring-brand-violet/40"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </header>

      <Tabs defaultValue="details">
        <TabsList>
          <TabsTab value="details">{s.details}</TabsTab>
          <TabsTab value="history">{s.history}</TabsTab>
        </TabsList>
        <TabsPanel value="details" className="flex flex-col gap-4 pt-4">
          <SourceFacts source={source} owner={owner} records={records} />
        </TabsPanel>
        <TabsPanel value="history" className="pt-4">
          <SourceHistory source={source} />
        </TabsPanel>
      </Tabs>

      <Link
        href={routes.source(source.id)}
        className="flex items-center gap-1 self-end rounded text-sm font-medium text-shell-nav-active outline-none hover:underline focus-visible:ring-2 focus-visible:ring-brand-violet/40"
      >
        {s.openDetail}
        <ArrowRight className="size-3.5" aria-hidden="true" />
      </Link>
    </aside>
  );
}

/** What a source is and where it stands: its last error first, if any. */
export function SourceFacts({
  source,
  owner,
  records,
}: {
  source: Source;
  owner: string;
  /** Read so far by the sync; undefined until a pass has read it. */
  records?: number;
}) {
  const t = useDictionary();
  const { locale } = useLocale();
  const s = t.sources.panel;
  const when = (iso: string | null | undefined) => (iso ? timeAgo(t, iso) : t.sources.never);
  const account = source.source_metadata.login ?? source.source_metadata.workspace;

  const general: MetadataItem[] = [
    { label: s.name, value: source.display_name },
    { label: s.type, value: sourceTitle(source.type) },
    {
      label: s.status,
      value: <StatusBadge variant={`connector.${source.status}`} size="sm" />,
    },
    {
      label: s.health,
      value: <StatusBadge variant={`health.${source.health_status}`} size="sm" />,
    },
    ...(account ? [{ label: s.account, value: String(account) }] : []),
    { label: s.lastSync, value: when(source.last_sync_at) },
    {
      label: s.records,
      value:
        records === undefined
          ? t.sources.notCounted
          : new Intl.NumberFormat(locale === "fr" ? "fr-FR" : "en-GB").format(records),
    },
    { label: s.lastCheck, value: when(source.last_health_check_at) },
    { label: s.owner, value: owner },
    { label: s.created, value: exactDate(locale, source.created_at) },
  ];
  if (source.credentials) {
    const value = fill(s.credentialsValue, {
      hint: source.credentials.hint,
      when: timeAgo(t, source.credentials.rotated_at).toLowerCase(),
    });
    general.push({ label: s.credentials, value });
  }

  return (
    <>
      {source.last_error ? <LastError diagnostic={source.last_error} /> : null}
      <MetadataPanel sections={[{ title: s.general, items: general }]} />
      <section>
        <h3 className="mb-2 text-sm font-semibold text-brand-navy">{s.reads}</h3>
        {source.capabilities.length > 0 ? (
          <ul className="flex flex-wrap gap-1.5">
            {source.capabilities.map((capability) => (
              <li
                key={capability}
                className="rounded-md bg-brand-violet-soft px-2 py-0.5 text-xs text-shell-nav-active"
              >
                {capabilityWord(t, capability, source.type)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-shell-muted">{s.notTested}</p>
        )}
      </section>
    </>
  );
}

function LastError({ diagnostic }: { diagnostic: Diagnostic }) {
  const t = useDictionary();
  return (
    <div role="alert" className="flex gap-2 rounded-lg bg-state-danger-soft p-3 text-sm">
      <TriangleAlert className="mt-0.5 size-4 shrink-0 text-state-danger" aria-hidden="true" />
      <div>
        <p className="font-medium text-brand-navy">
          {t.sources.panel.lastError} — {diagnostic.message}
        </p>
        <p className="mt-1 text-shell-muted">{diagnostic.remediation}</p>
      </div>
    </div>
  );
}

export function SourceHistory({ source, limit = 20 }: { source: Source; limit?: number }) {
  const t = useDictionary();
  const events = useSourceEvents(source.id, limit);
  if (events.isError)
    return <p className="text-sm text-shell-muted">{t.sources.panel.historyFailed}</p>;
  if (!events.data) return null;
  if (events.data.length === 0) {
    return <p className="text-sm text-shell-muted">{t.sources.panel.noHistory}</p>;
  }
  return <EventTimeline events={events.data.map((event) => timelineEvent(t, event))} compact />;
}

/** A source event, in the timeline's vocabulary. */
export function timelineEvent(t: Dictionary, event: SourceEvent): TimelineEvent {
  const words = t.sources.events;
  const payload = event.payload as Record<string, unknown>;
  const health = t.knowledge.status.health as Record<string, string>;
  const title =
    event.type === "health_changed"
      ? fill(words.health_changed, {
          previous: health[String(payload.previous)] ?? String(payload.previous),
          current: health[String(payload.current)] ?? String(payload.current),
        })
      : event.type === "settings_changed"
        ? fill(words.settings_changed, { version: String(payload.version) })
        : words[event.type];
  const failed =
    event.type === "test_failed" || event.type === "deleted" || event.type === "sync_failed";
  return {
    id: event.id,
    type: event.type === "health_changed" || failed ? "health_change" : "change",
    title,
    at: event.created_at,
    subtitle: typeof payload.code === "string" ? payload.code : undefined,
  };
}

/**
 * What a capability is called, in the vendor's own terms when the source's
 * kind is known — "buckets S3" at AWS, "comptes de stockage" at Azure — and
 * in general terms otherwise.
 */
export function capabilityWord(t: Dictionary, capability: string, kind?: string): string {
  const ofKind = kind
    ? (t.sources.capabilitiesOf as Record<string, Record<string, string> | undefined>)[kind]
    : undefined;
  return (
    ofKind?.[capability] ??
    (t.sources.capabilities as Record<string, string>)[capability] ??
    capability
  );
}
