"use client";

import { KnowledgeTable, type KnowledgeColumn } from "@/components/knowledge/knowledge-table";
import { MetadataPanel } from "@/components/knowledge/metadata-panel";
import { StatusBadge } from "@/components/knowledge/status-badge";
import { exactDate, timeAgo } from "@/components/knowledge/time";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { receivingAddress, type Source, type WebhookDelivery } from "@/lib/sources";
import { useCatalog, useSourceDeliveries } from "@/lib/sources-queries";

/**
 * A source its system SENDS to — a webhook (LEKA-350): the address to give
 * that system, how it signs, and what it sent, newest first — kept, waiting
 * for its pass, stored, ignored, or refused and why. Never a body: the API
 * does not return one.
 *
 * Nothing for a source LEKA reads: the catalogue says which kinds receive.
 */
export function SourceReceptionSection({ source }: { source: Source }) {
  const catalog = useCatalog();
  const receives = catalog.data?.find((entry) => entry.key === source.type)?.receives ?? false;
  if (!receives) return null;
  return <Reception source={source} />;
}

type Status = "pending" | "stored" | "ignored" | "rejected";

const LOOK = {
  pending: "source.setup",
  stored: "source.synced",
  ignored: "source.off",
  rejected: "sync.failed",
} as const satisfies Record<Status, string>;

function Reception({ source }: { source: Source }) {
  const t = useDictionary();
  const { locale } = useLocale();
  const w = t.sources.reception;
  const deliveries = useSourceDeliveries(source.id);
  const number = new Intl.NumberFormat(locale === "fr" ? "fr-FR" : "en-GB");
  const address = receivingAddress(source.id);
  const mode =
    typeof source.config.signature === "string" ? source.config.signature : "hmac_sha256";
  const header =
    typeof source.config.signature_header === "string" && source.config.signature_header
      ? source.config.signature_header
      : mode === "token"
        ? "X-Leka-Token"
        : "X-Leka-Signature";
  const signature = (w.signatures as Record<string, string>)[mode];

  const columns: KnowledgeColumn<WebhookDelivery>[] = [
    {
      id: "received",
      header: w.received,
      cell: (delivery) => (
        <span title={exactDate(locale, delivery.received_at)}>
          {timeAgo(t, delivery.received_at)}
        </span>
      ),
    },
    {
      id: "status",
      header: w.status,
      cell: (delivery) => (
        <StatusBadge
          variant={LOOK[delivery.status as Status] ?? "sync.failed"}
          label={(w.statuses as Record<string, string>)[delivery.status] ?? delivery.status}
          size="sm"
        />
      ),
    },
    { id: "resource", header: w.resource, cell: (delivery) => delivery.resource ?? "—" },
    {
      id: "records",
      header: w.records,
      align: "end",
      cell: (delivery) => {
        const records = number.format(delivery.records);
        if (!delivery.gone) return records;
        return `${records} · ${fill(w.gone, { count: number.format(delivery.gone) })}`;
      },
    },
    { id: "reason", header: w.reason, cell: (delivery) => <Why delivery={delivery} /> },
  ];

  return (
    <section className="rounded-xl border border-shell-line bg-white p-4">
      <h2 className="mb-1 text-lg font-semibold text-brand-navy">{w.title}</h2>
      <p className="mb-3 text-sm text-shell-muted">{w.intro}</p>
      <MetadataPanel
        sections={[
          {
            items: [
              {
                label: w.address,
                value: <code className="break-all">{address}</code>,
                copyValue: address,
              },
              { label: w.signature, value: signature ? fill(signature, { header }) : mode },
            ],
          },
        ]}
      />
      {source.status === "active" || source.status === "degraded" ? null : (
        <p role="status" className="mt-3 text-sm text-state-warning">
          {w.inactive}
        </p>
      )}
      <h3 className="mt-4 mb-2 text-sm font-semibold text-brand-navy">{w.deliveries}</h3>
      {deliveries.isError ? (
        <p className="text-sm text-shell-muted">{w.loadFailed}</p>
      ) : deliveries.data && deliveries.data.length === 0 ? (
        <p className="text-sm text-shell-muted">{w.empty}</p>
      ) : (
        <KnowledgeTable
          caption={w.caption}
          columns={columns}
          rows={deliveries.data ?? []}
          rowKey={(delivery) => delivery.id}
          loading={deliveries.isPending}
        />
      )}
    </section>
  );
}

/** Why it was not stored: the reason in the reader's words, the API's detail under it. */
function Why({ delivery }: { delivery: WebhookDelivery }) {
  const w = useDictionary().sources.reception;
  if (delivery.status === "ignored") {
    return <span className="text-xs text-shell-muted">{w.ignoredWhy}</span>;
  }
  if (delivery.status !== "rejected" || !delivery.error) return null;
  const reason = String(delivery.error.reason ?? "");
  return (
    <div className="max-w-72">
      <p className="text-xs font-medium text-state-danger">
        {(w.reasons as Record<string, string>)[reason] ?? reason}
      </p>
      <p className="text-xs text-shell-muted">{String(delivery.error.message ?? "")}</p>
    </div>
  );
}
