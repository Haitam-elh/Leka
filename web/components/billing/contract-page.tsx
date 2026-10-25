"use client";

import { BadgeCheck, Building2, ImageUp, Mail, ReceiptText, Trash2, Users } from "lucide-react";
import { useRef } from "react";

import { Card } from "@/components/environment/parts";
import { usePermissions } from "@/components/shell/shell-provider";
import { PageContainer, PageHeader } from "@/components/shell/page-container";
import { StatCard, StatGrid } from "@/components/shell/stat-card";
import { ErrorState } from "@/components/states/error-state";
import { Button } from "@/components/ui/button";
import { routes } from "@/config/routes";
import { agentTitle } from "@/lib/agent-title";
import { ApiError } from "@/lib/api";
import { useAddOns } from "@/lib/billing-queries";
import {
  LOGO_MAX_BYTES,
  LOGO_TYPES,
  logoAddress,
  useContract,
  useGiveLogo,
  useLogo,
  useRemoveLogo,
} from "@/lib/contract";
import { fill } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { notify } from "@/lib/notify";

/**
 * « Contrat » (2026-10-25): what « Facturation » is under an Enterprise
 * contract — its type and since when, the organisation, its members, its
 * dedicated contact, what it includes; its logo, for its admin to give.
 * Never a price, never credits, never a plan to change: the contract is
 * agreed with LEKA.
 */
export function ContractScreen() {
  const t = useDictionary();
  const w = t.billing.contract;
  const { format } = useLocale();
  const contract = useContract();
  const dedicated = useAddOns().data?.dedicated ?? [];
  const data = contract.data;
  const day = (iso: string) => new Intl.DateTimeFormat(format, { dateStyle: "long" }).format(new Date(iso));

  return (
    <PageContainer>
      <PageHeader title={w.title} subtitle={w.subtitle} />
      {contract.isError ? (
        <ErrorState error={contract.error} onRetry={() => void contract.refetch()} />
      ) : !data ? (
        <div className="h-72 animate-pulse rounded-xl bg-shell-canvas" aria-hidden="true" />
      ) : (
        <div className="flex flex-col gap-4" data-testid="contract">
          <StatGrid count={4}>
            <StatCard
              icon={ReceiptText}
              tone="violet"
              value={w.enterprise}
              label={w.type}
              foot={data.since ? fill(w.since, { date: day(data.since) }) : null}
              testId="contract-type"
            />
            <StatCard icon={Building2} tone="violet" value={data.organisation} label={w.organisation} testId="contract-organisation" />
            <StatCard
              icon={Users}
              tone="info"
              value={new Intl.NumberFormat(format).format(data.members)}
              label={w.members}
              foot={w.membersFoot}
              href={routes.team()}
              testId="contract-members"
            />
            <StatCard
              icon={Mail}
              tone="success"
              value={data.contact?.name ?? "—"}
              label={w.contact}
              foot={data.contact?.email ?? (data.contact ? null : w.noContact)}
              testId="contract-contact"
            />
          </StatGrid>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card title={w.includesTitle} icon={<BadgeCheck className="size-4 text-shell-muted" aria-hidden="true" />}>
              <ul className="flex list-disc flex-col gap-1.5 ps-5 text-[0.875rem] text-brand-navy" data-testid="contract-includes">
                {dedicated.length ? (
                  <li>{fill(w.dedicated, { names: dedicated.map((key) => agentTitle(t, key, key)).join(", ") })}</li>
                ) : null}
                {w.includes.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </Card>
            <LogoCard organisation={data.organisation} />
          </div>
        </div>
      )}
    </PageContainer>
  );
}

/** Its logo: text — its name — by default; an image its admin gives. */
function LogoCard({ organisation }: { organisation: string }) {
  const t = useDictionary();
  const w = t.billing.contract;
  const admin = usePermissions()?.includes("workspace:update") ?? false;
  const logo = useLogo();
  const give = useGiveLogo();
  const remove = useRemoveLogo();
  const input = useRef<HTMLInputElement>(null);

  function refused(error: unknown) {
    notify.error({ title: error instanceof ApiError ? error.message : String(error) });
  }

  function chosen(file: File | undefined) {
    if (!file) return;
    if (!(LOGO_TYPES as readonly string[]).includes(file.type)) {
      notify.error({ title: w.logoType });
      return;
    }
    if (file.size > LOGO_MAX_BYTES) {
      notify.error({ title: w.logoTooLarge });
      return;
    }
    give.mutate(file, { onSuccess: () => notify.success({ title: w.logoGiven }), onError: refused });
  }

  return (
    <Card title={w.logoTitle} icon={<ImageUp className="size-4 text-shell-muted" aria-hidden="true" />}>
      <div className="flex flex-col gap-3" data-testid="contract-logo">
        <p className="text-[0.8125rem] text-shell-muted">{w.logoLead}</p>
        <div className="flex h-16 items-center rounded-lg border border-dashed border-shell-line bg-shell-canvas/50 px-4">
          {logo ? (
            // eslint-disable-next-line @next/next/no-img-element -- the API serves it, sized by the box
            <img
              src={logoAddress(logo)}
              alt={fill(w.logoAlt, { name: organisation })}
              className="max-h-10 max-w-48 object-contain"
              data-testid="contract-logo-image"
            />
          ) : (
            <span className="text-[0.875rem] font-semibold text-brand-navy" data-testid="contract-logo-text">
              {organisation}
            </span>
          )}
        </div>
        {logo ? null : <p className="text-xs text-shell-muted">{w.logoNone}</p>}
        {admin ? (
          <div className="flex flex-wrap gap-2">
            <input
              ref={input}
              type="file"
              accept={LOGO_TYPES.join(",")}
              className="sr-only"
              tabIndex={-1}
              aria-hidden="true"
              onChange={(event) => {
                chosen(event.target.files?.[0]);
                event.target.value = "";
              }}
              data-testid="contract-logo-input"
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={give.isPending}
              onClick={() => input.current?.click()}
              data-testid="contract-logo-give"
            >
              <ImageUp aria-hidden="true" />
              {logo ? w.logoReplace : w.logoGive}
            </Button>
            {logo ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(undefined, {
                    onSuccess: () => notify.success({ title: w.logoRemoved }),
                    onError: refused,
                  })
                }
                data-testid="contract-logo-remove"
              >
                <Trash2 aria-hidden="true" />
                {w.logoRemove}
              </Button>
            ) : null}
          </div>
        ) : (
          <p className="text-xs text-shell-muted">{w.logoAdminOnly}</p>
        )}
      </div>
    </Card>
  );
}
