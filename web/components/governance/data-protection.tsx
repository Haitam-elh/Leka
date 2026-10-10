"use client";

import { Archive, Database, KeyRound, Lock, ScanSearch, Shield, Users } from "lucide-react";
import { useState } from "react";

import { Card } from "@/components/environment/parts";
import { Pill } from "@/components/intelligence/pill";
import { usePermissions } from "@/components/shell/shell-provider";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { type Dictionary, fill } from "@/lib/i18n/dictionaries";
import { useDictionary } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";
import type { Posture, ProtectionPolicy, SourceFindings } from "@/lib/protection";
import { useDataProtection, useSetProtectionPolicy } from "@/lib/protection-queries";

/**
 * Sécurité & gouvernance › Données (LEKA-405): how the platform protects
 * data, read from it as it runs — the database connection's TLS, how
 * collected files are encrypted, the credentials' encryption and keys, the
 * isolation between workspaces, the session cookie; what LEKA found in each
 * source's records and masked — kinds and counts, never a value; and how
 * long an original holding a secret is kept, which a manager changes.
 */

function kindsSaid(t: Dictionary, found: Record<string, number>): string | null {
  const names = t.protection.kinds as Record<string, string>;
  const parts = Object.entries(found).map(([kind, n]) => `${names[kind] ?? kind} × ${n}`);
  return parts.length ? parts.join(", ") : null;
}

function Line({
  icon,
  label,
  value,
  ok,
  testid,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  ok: boolean | null;
  testid: string;
}) {
  return (
    <li className="flex items-start gap-3 border-t border-shell-line pt-2 text-[0.8125rem]" data-testid={testid}>
      <span className="mt-0.5 text-shell-muted">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block font-medium text-brand-navy">{label}</span>
        <span className="block text-shell-muted">{value}</span>
      </span>
      <Pill tone={ok === null ? "neutral" : ok ? "success" : "warning"}>
        {ok === null ? "?" : ok ? "✓" : "!"}
      </Pill>
    </li>
  );
}

function PlatformCard({ posture }: { posture: Posture }) {
  const t = useDictionary();
  const w = t.protection;
  const transit =
    posture.database_tls === null
      ? w.transitUnknown
      : posture.database_tls
        ? fill(w.transitOn, { version: posture.database_tls_version ? ` ${posture.database_tls_version}` : "" })
        : w.transitOff;
  const rest =
    posture.object_store === "local"
      ? w.restLocal
      : posture.object_store_encryption
        ? fill(w.restS3, { how: posture.object_store_encryption })
        : w.restS3Provider;
  return (
    <Card title={w.platform} icon={<Shield className="size-4 text-shell-muted" aria-hidden="true" />}>
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.platformSaid}</p>
      <ul className="flex flex-col gap-2" data-testid="platform-protections">
        <Line
          icon={<Lock className="size-4" aria-hidden="true" />}
          label={w.transit}
          value={transit}
          ok={posture.database_tls}
          testid="protection-transit"
        />
        <Line
          icon={<Archive className="size-4" aria-hidden="true" />}
          label={w.rest}
          value={rest}
          ok={posture.object_store === "s3"}
          testid="protection-rest"
        />
        <Line
          icon={<KeyRound className="size-4" aria-hidden="true" />}
          label={w.credentials}
          value={`${fill(w.credentialsSaid, { count: posture.credential_keys })} · ${
            posture.overdue_secrets.length
              ? fill(w.overdue, { list: posture.overdue_secrets.join(", ") })
              : w.noOverdue
          }`}
          ok={posture.overdue_secrets.length === 0}
          testid="protection-credentials"
        />
        <Line
          icon={<Users className="size-4" aria-hidden="true" />}
          label={w.isolation}
          value={w.isolationSaid}
          ok
          testid="protection-isolation"
        />
        <Line
          icon={<Database className="size-4" aria-hidden="true" />}
          label={w.cookie}
          value={posture.session_cookie_secure ? w.cookieOn : w.cookieOff}
          ok={posture.session_cookie_secure}
          testid="protection-cookie"
        />
      </ul>
    </Card>
  );
}

function FoundCard({ sources }: { sources: SourceFindings[] }) {
  const t = useDictionary();
  const w = t.protection;
  return (
    <Card title={w.found} icon={<ScanSearch className="size-4 text-shell-muted" aria-hidden="true" />}>
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.foundSaid}</p>
      {sources.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-[0.8125rem]" data-testid="protection-found">
            <thead>
              <tr className="text-left text-xs text-shell-muted">
                {(["source", "scanned", "withSecrets", "secrets", "personal"] as const).map((c) => (
                  <th key={c} scope="col" className="px-2 py-1 font-medium">
                    {w.columns[c]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s.source_id} className="border-t border-shell-line align-top" data-source={s.source_id}>
                  <th scope="row" className="px-2 py-1.5 text-left font-medium text-brand-navy">
                    {s.name ?? s.source_id.slice(0, 8)}
                    {s.kind ? <span className="block text-xs font-normal text-shell-muted">{s.kind}</span> : null}
                  </th>
                  <td className="px-2 py-1.5 tabular-nums">
                    {fill(w.scannedOf, { scanned: s.scanned, records: s.records })}
                  </td>
                  <td className="px-2 py-1.5 tabular-nums">
                    {s.with_secrets ? <Pill tone="warning">{s.with_secrets}</Pill> : w.none}
                  </td>
                  <td className="px-2 py-1.5">{kindsSaid(t, s.secrets) ?? w.none}</td>
                  <td className="px-2 py-1.5">{kindsSaid(t, s.personal_data) ?? w.none}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-[0.8125rem] text-shell-muted">{w.noSource}</p>
      )}
    </Card>
  );
}

function PolicyCard({ policy, editable }: { policy: ProtectionPolicy; editable: boolean }) {
  const t = useDictionary();
  const w = t.protection;
  const save = useSetProtectionPolicy();
  const [days, setDays] = useState(policy.found_payload_days);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    try {
      await save.mutateAsync(days);
      notify.success({ title: w.saved });
    } catch (error) {
      notify.error({ title: error instanceof ApiError ? error.message : w.failed });
    }
  }

  return (
    <Card
      title={w.policy}
      icon={<Archive className="size-4 text-shell-muted" aria-hidden="true" />}
      action={<Pill tone={policy.customised ? "violet" : "neutral"}>{policy.customised ? w.customised : w.byDefault}</Pill>}
    >
      <p className="mb-3 text-[0.8125rem] text-shell-muted">{w.policySaid}</p>
      <form className="flex flex-wrap items-end gap-2 text-[0.8125rem]" onSubmit={(e) => void submit(e)} data-testid="protection-policy">
        <label className="flex flex-col gap-1">
          <span className="text-shell-muted">{w.days}</span>
          <select
            className="rounded-md border border-shell-line bg-white px-2 py-1.5 text-brand-navy disabled:bg-shell-canvas"
            value={days}
            disabled={!editable}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            {Array.from({ length: 30 }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        {editable ? (
          <Button type="submit" disabled={save.isPending || days === policy.found_payload_days}>
            {w.save}
          </Button>
        ) : (
          <p className="text-xs text-shell-muted">{w.readOnly}</p>
        )}
      </form>
    </Card>
  );
}

export function DataProtection() {
  const permissions = usePermissions() ?? [];
  const query = useDataProtection();
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (!query.data) return <div className="h-96 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />;
  const { posture, policy, sources } = query.data;
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" data-testid="data-protection">
      <div className="flex flex-col gap-4">
        <PlatformCard posture={posture} />
        <PolicyCard
          key={policy.found_payload_days}
          policy={policy}
          editable={permissions.includes("policy:manage")}
        />
      </div>
      <FoundCard sources={sources} />
    </div>
  );
}
